"""Relationship lifecycle: the only way a relationship changes status.

Every transition:
  - is validated by app.validation.state_guard
  - requires a linked claim (no claim -> no verification, provenance is mandatory)
  - appends to relationship_history with actor, reason, evidence and a snapshot
  - never deletes anything
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
    assert_transition_allowed,
    evaluate_promotion,
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


async def _load_evidence_facts(
    session: AsyncSession, relationship_id: uuid.UUID
) -> list[EvidenceFact]:
    stmt = (
        select(Evidence)
        .join(RelationshipEvidence, RelationshipEvidence.evidence_id == Evidence.id)
        .where(RelationshipEvidence.relationship_id == relationship_id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        EvidenceFact(
            evidence_id=str(e.id),
            grade=e.evidence_grade,
            content_hash=e.content_hash,
            relation="supporting",
        )
        for e in rows
    ]


async def _load_claim_types(
    session: AsyncSession, relationship_id: uuid.UUID
) -> list[str]:
    stmt = (
        select(Claim.claim_type)
        .join(ClaimRelationship, ClaimRelationship.claim_id == Claim.id)
        .where(ClaimRelationship.relationship_id == relationship_id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def transition(
    session: AsyncSession,
    relationship_id: uuid.UUID,
    to_status: RelationshipStatus | str,
    *,
    actor: str,
    reason: str | None = None,
    evidence_ids: Sequence[uuid.UUID] | None = None,
) -> Relationship:
    """Move a relationship to `to_status`, enforcing every guard.

    Idempotent: moving to the current status returns the row untouched.
    """
    target = RelationshipStatus(to_status)

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

    current = RelationshipStatus(rel.status)
    if current == target:
        return rel

    assert_transition_allowed(current, target)

    if target is RelationshipStatus.VERIFIED:
        claim_types = await _load_claim_types(session, relationship_id)
        if not claim_types:
            raise AppError(
                ErrorCode.EVIDENCE_REQUIRED,
                "Relationship has no supporting claim; provenance is mandatory",
                details={"relationship_id": str(relationship_id)},
            )
        facts = await _load_evidence_facts(session, relationship_id)
        # Judge against the weakest claim type: one inferred claim poisons the batch.
        for ctype in claim_types:
            decision = evaluate_promotion(ctype, facts)
            decision.raise_if_denied()
        if decision.target_status is not RelationshipStatus.VERIFIED:
            raise AppError(
                ErrorCode.EVIDENCE_REQUIRED,
                "Conflicting evidence exists; relationship can only be disputed",
                details={"reasons": decision.reasons},
            )

    rel.status = target.value
    rel.version = rel.version + 1
    if target is RelationshipStatus.VERIFIED:
        rel.last_verified_at = datetime.now(UTC)

    session.add(
        RelationshipHistory(
            relationship_id=rel.id,
            from_status=current.value,
            to_status=target.value,
            actor=actor,
            reason=reason,
            evidence_ids=list(evidence_ids or []),
            snapshot=_snapshot(rel),
        )
    )
    await session.flush()
    return rel


__all__ = ["transition"]
