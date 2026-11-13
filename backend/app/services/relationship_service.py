"""Relationship lifecycle: the only way a relationship changes status.

Rules (ADR-0008 + reviewer decisions 2026-11-13):

* `candidate -> pending_review`  requires the evidence threshold. No approval needed.
* `pending_review -> verified`   requires the threshold AND an explicit approval.
                                  The threshold alone never verifies anything.
* `verified -> disputed`         requires at least one contradicting evidence item;
                                  the original supporting evidence is kept.
* Nothing is ever deleted. Every move appends to relationship_history with
  actor / trigger / reason / evidence ids / full snapshot.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models.claim import Claim, ClaimRelationship
from app.models.evidence import Evidence
from app.models.relationship import Relationship, RelationshipEvidence, RelationshipHistory
from app.schemas.enums import RelationshipStatus
from app.validation.state_guard import (
    EvidenceFact,
    EvidenceThreshold,
    assert_can_dispute,
    assert_transition_allowed,
    evaluate_review_eligibility,
    evaluate_verification,
)

#: Statuses the generic `transition` helper is allowed to drive.
GENERIC_TARGETS = frozenset(
    {
        RelationshipStatus.REJECTED,
        RelationshipStatus.REVOKED,
        RelationshipStatus.EXPIRED,
    }
)


def _snapshot(rel: Relationship) -> dict:
    return {
        "id": str(rel.id),
        "source_entity_id": str(rel.source_entity_id),
        "target_entity_id": str(rel.target_entity_id),
        "relationship_type": rel.relationship_type,
        "status": rel.status,
        "confidence": float(rel.confidence),
        "valid_from": rel.valid_from.isoformat() if rel.valid_from else None,
        "valid_to": rel.valid_to.isoformat() if rel.valid_to else None,
        "version": rel.version,
    }


async def _load_relationship(
    session: AsyncSession, relationship_id: uuid.UUID
) -> Relationship:
    rel = (
        await session.execute(
            select(Relationship).where(Relationship.id == relationship_id).with_for_update()
        )
    ).scalar_one_or_none()
    if rel is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            "Relationship not found",
            details={"relationship_id": str(relationship_id)},
        )
    return rel


async def _load_evidence_facts(
    session: AsyncSession, relationship_id: uuid.UUID
) -> list[EvidenceFact]:
    stmt = (
        select(Evidence, RelationshipEvidence.relation)
        .join(RelationshipEvidence, RelationshipEvidence.evidence_id == Evidence.id)
        .where(RelationshipEvidence.relationship_id == relationship_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        EvidenceFact(
            evidence_id=str(evidence.id),
            grade=evidence.evidence_grade,
            origin_key=evidence.origin_key,
            relation=relation,
        )
        for evidence, relation in rows
    ]


async def _load_claim_types(session: AsyncSession, relationship_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Claim.claim_type)
        .join(ClaimRelationship, ClaimRelationship.claim_id == Claim.id)
        .where(ClaimRelationship.relationship_id == relationship_id)
    )
    return list((await session.execute(stmt)).scalars().all())


def _append_history(
    session: AsyncSession,
    rel: Relationship,
    *,
    from_status: RelationshipStatus,
    actor: str,
    trigger: str,
    reason: str | None,
    evidence_ids: Sequence[uuid.UUID] | None,
) -> None:
    session.add(
        RelationshipHistory(
            relationship_id=rel.id,
            from_status=from_status.value,
            to_status=rel.status,
            actor=actor,
            trigger=trigger,
            reason=reason,
            evidence_ids=list(evidence_ids or []),
            snapshot=_snapshot(rel),
        )
    )


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


async def submit_for_review(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    *,
    actor: str,
    reason: str | None = None,
    threshold: EvidenceThreshold | None = None,
) -> Relationship:
    """candidate -> pending_review. Gated by the evidence threshold only."""
    rel = await _load_relationship(session, relationship_id)
    current = RelationshipStatus(rel.status)
    if current is RelationshipStatus.PENDING_REVIEW:
        return rel
    assert_transition_allowed(current, RelationshipStatus.PENDING_REVIEW)

    claim_types = await _load_claim_types(session, relationship_id)
    if not claim_types:
        raise AppError(
            ErrorCode.EVIDENCE_REQUIRED,
            "Relationship has no supporting claim; provenance is mandatory",
            details={"relationship_id": str(relationship_id)},
        )

    facts = await _load_evidence_facts(session, relationship_id)
    for ctype in claim_types:
        decision = evaluate_review_eligibility(ctype, facts, threshold or EvidenceThreshold())
        decision.raise_if_denied()

    rel.status = RelationshipStatus.PENDING_REVIEW.value
    rel.version += 1
    _append_history(
        session,
        rel,
        from_status=current,
        actor=actor,
        trigger="evidence_threshold",
        reason=reason,
        evidence_ids=None,
    )
    await session.flush()
    return rel


async def verify(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    *,
    approved_by: str,
    reason: str | None = None,
    evidence_ids: Sequence[uuid.UUID] | None = None,
    threshold: EvidenceThreshold | None = None,
) -> Relationship:
    """pending_review -> verified. Threshold + explicit approval, never automatic."""
    rel = await _load_relationship(session, relationship_id)
    current = RelationshipStatus(rel.status)
    if current is RelationshipStatus.VERIFIED:
        return rel
    assert_transition_allowed(current, RelationshipStatus.VERIFIED)

    claim_types = await _load_claim_types(session, relationship_id)
    if not claim_types:
        raise AppError(
            ErrorCode.EVIDENCE_REQUIRED,
            "Relationship has no supporting claim; provenance is mandatory",
            details={"relationship_id": str(relationship_id)},
        )

    facts = await _load_evidence_facts(session, relationship_id)
    for ctype in claim_types:
        decision = evaluate_verification(
            ctype, facts, approved_by=approved_by, threshold=threshold or EvidenceThreshold()
        )
        decision.raise_if_denied()

    rel.status = RelationshipStatus.VERIFIED.value
    rel.version += 1
    rel.last_verified_at = datetime.now(UTC)
    _append_history(
        session,
        rel,
        from_status=current,
        actor=approved_by,
        trigger="manual_approval",
        reason=reason,
        evidence_ids=evidence_ids,
    )
    await session.flush()
    return rel


async def dispute(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    *,
    actor: str,
    reason: str,
    contradicting_evidence_ids: Sequence[uuid.UUID],
) -> Relationship:
    """verified -> disputed. New evidence challenges an established fact.

    Both sides are preserved: the existing supporting rows stay untouched and the
    contradicting items are attached with relation='contradicting'.
    """
    assert_can_dispute([str(e) for e in contradicting_evidence_ids])

    rel = await _load_relationship(session, relationship_id)
    current = RelationshipStatus(rel.status)
    if current is RelationshipStatus.DISPUTED:
        return rel
    assert_transition_allowed(current, RelationshipStatus.DISPUTED)

    existing = set(
        (
            await session.execute(
                select(RelationshipEvidence.evidence_id).where(
                    RelationshipEvidence.relationship_id == relationship_id,
                    RelationshipEvidence.relation == "contradicting",
                )
            )
        ).scalars()
    )

    for evidence_id in contradicting_evidence_ids:
        evidence = (
            await session.execute(select(Evidence).where(Evidence.id == evidence_id))
        ).scalar_one_or_none()
        if evidence is None:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "Contradicting evidence not found",
                details={"evidence_id": str(evidence_id)},
            )
        if evidence_id not in existing:
            session.add(
                RelationshipEvidence(
                    relationship_id=relationship_id,
                    evidence_id=evidence_id,
                    relation="contradicting",
                )
            )

    rel.status = RelationshipStatus.DISPUTED.value
    rel.version += 1
    _append_history(
        session,
        rel,
        from_status=current,
        actor=actor,
        trigger="new_evidence",
        reason=reason,
        evidence_ids=contradicting_evidence_ids,
    )
    await session.flush()
    return rel


async def transition(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    to_status: RelationshipStatus | str,
    *,
    actor: str,
    reason: str | None = None,
    evidence_ids: Sequence[uuid.UUID] | None = None,
) -> Relationship:
    """Generic helper for reject / revoke / expire.

    Verification and disputing have their own entry points because they carry
    extra preconditions; routing them through here would bypass those checks.
    """
    target = RelationshipStatus(to_status)
    if target not in GENERIC_TARGETS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"status {target.value} must be set via its dedicated operation",
            details={
                "status": target.value,
                "generic_allowed": sorted(s.value for s in GENERIC_TARGETS),
            },
        )

    rel = await _load_relationship(session, relationship_id)
    current = RelationshipStatus(rel.status)
    if current is target:
        return rel
    assert_transition_allowed(current, target)

    rel.status = target.value
    rel.version += 1
    _append_history(
        session,
        rel,
        from_status=current,
        actor=actor,
        trigger="manual",
        reason=reason,
        evidence_ids=evidence_ids,
    )
    await session.flush()
    return rel


__all__ = ["GENERIC_TARGETS", "dispute", "submit_for_review", "transition", "verify"]
