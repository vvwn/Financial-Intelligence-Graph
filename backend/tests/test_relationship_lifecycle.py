"""Integration tests: the relationship lifecycle against a live PostgreSQL.

Covers the reviewer decisions of 2026-11-13:
  - threshold only grants review entry, never verification
  - verification requires explicit human/QA approval
  - disputed is only reachable from verified and preserves both sides
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError, ErrorCode
from app.models.relationship import Relationship, RelationshipEvidence, RelationshipHistory
from app.services.relationship_service import (
    dispute,
    submit_for_review,
    transition,
    verify,
)
from factories import (
    add_evidence,
    link_claim,
    link_evidence,
    make_claim,
    make_entity,
    make_evidence,
    make_relationship,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db

_CODE_SEQ = {"n": 0}


def _next_code() -> str:
    _CODE_SEQ["n"] += 1
    return f"{700000 + _CODE_SEQ['n']:06d}"


async def _seed(
    session: AsyncSession,
    *,
    grades: list[str],
    origins: list[str] | None = None,
    claim_type: str = "fact_reported",
    status: str = "candidate",
    relationship_type: str = "supplies_to",
):
    supplier = await make_entity(session, f"光模块股份{_next_code()}", _next_code())
    customer = await make_entity(session, f"云科技{_next_code()}", _next_code())
    rel = await make_relationship(
        session, supplier, customer, status=status, relationship_type=relationship_type
    )
    claim = await make_claim(session, supplier, customer, claim_type=claim_type)
    await link_claim(session, claim, rel)
    for index, grade in enumerate(grades):
        origin = origins[index] if origins else uuid.uuid4().hex
        ev = await add_evidence(session, make_evidence(grade, origin_key=origin))
        await link_evidence(session, rel, ev, claim)
    return rel, claim


async def _history(session: AsyncSession, rel_id: uuid.UUID) -> list[RelationshipHistory]:
    return list(
        (
            await session.execute(
                select(RelationshipHistory)
                .where(RelationshipHistory.relationship_id == rel_id)
                .order_by(RelationshipHistory.created_at)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# candidate -> pending_review (threshold only)
# ---------------------------------------------------------------------------


async def test_threshold_grants_review_entry(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"])

    updated = await submit_for_review(session, rel.id, actor="system:pipeline")

    assert updated.status == "pending_review"
    history = await _history(session, rel.id)
    assert history[-1].trigger == "evidence_threshold"
    assert history[-1].to_status == "pending_review"


async def test_single_grade_c_cannot_enter_review(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["C"])

    with pytest.raises(AppError) as exc:
        await submit_for_review(session, rel.id, actor="system:pipeline")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED
    assert rel.status == "candidate"


async def test_reposts_of_one_origin_cannot_enter_review(
    session: AsyncSession, clean_db: None
) -> None:
    """Two C-grade rows from the same origin are one source, not two."""
    rel, _ = await _seed(session, grades=["C", "C"], origins=["origin-x", "origin-x"])

    with pytest.raises(AppError) as exc:
        await submit_for_review(session, rel.id, actor="system:pipeline")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED


async def test_two_independent_c_origins_enter_review(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed(session, grades=["C", "C"], origins=["origin-a", "origin-b"])

    updated = await submit_for_review(session, rel.id, actor="system:pipeline")
    assert updated.status == "pending_review"


async def test_inferred_claim_never_enters_review(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"], claim_type="inferred")

    with pytest.raises(AppError) as exc:
        await submit_for_review(session, rel.id, actor="system:pipeline")
    assert exc.value.code is ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE


async def test_no_claim_blocks_review(session: AsyncSession, clean_db: None) -> None:
    supplier = await make_entity(session, "无来源股份", _next_code())
    customer = await make_entity(session, "无来源客户", _next_code())
    rel = await make_relationship(session, supplier, customer)
    ev = await add_evidence(session, make_evidence("A"))
    await link_evidence(session, rel, ev)

    with pytest.raises(AppError) as exc:
        await submit_for_review(session, rel.id, actor="system:pipeline")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED


# ---------------------------------------------------------------------------
# pending_review -> verified (explicit approval required)
# ---------------------------------------------------------------------------


async def test_threshold_alone_does_not_verify(session: AsyncSession, clean_db: None) -> None:
    """The central rule: meeting the threshold must not set verified by itself."""
    rel, _ = await _seed(session, grades=["A"], status="pending_review")

    with pytest.raises(AppError) as exc:
        await verify(session, rel.id, approved_by="")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED
    assert any("explicit approval" in r for r in exc.value.details["reasons"])
    assert rel.status == "pending_review"


async def test_automated_actor_cannot_verify(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"], status="pending_review")

    with pytest.raises(AppError):
        await verify(session, rel.id, approved_by="system:auto-pipeline")


async def test_human_approval_verifies(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"], status="pending_review")

    updated = await verify(session, rel.id, approved_by="human:kevin", reason="公告核对")

    assert updated.status == "verified"
    assert updated.last_verified_at is not None
    history = await _history(session, rel.id)
    assert history[-1].trigger == "manual_approval"
    assert history[-1].actor == "human:kevin"


async def test_verification_is_idempotent(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"], status="pending_review")
    first = await verify(session, rel.id, approved_by="human:kevin")
    second = await verify(session, rel.id, approved_by="human:kevin")
    assert first.version == second.version


# ---------------------------------------------------------------------------
# verified -> disputed
# ---------------------------------------------------------------------------


async def test_dispute_from_pending_review_is_illegal(
    session: AsyncSession, clean_db: None
) -> None:
    """disputed means "a verified fact was challenged", not "still checking"."""
    rel, _ = await _seed(session, grades=["A"], status="pending_review")
    counter = await add_evidence(session, make_evidence("A"))

    with pytest.raises(AppError) as exc:
        await dispute(
            session,
            rel.id,
            actor="human:kevin",
            reason="新证据",
            contradicting_evidence_ids=[counter.id],
        )
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID


async def test_dispute_requires_contradicting_evidence(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed(session, grades=["A"], status="verified")

    with pytest.raises(AppError) as exc:
        await dispute(
            session,
            rel.id,
            actor="human:kevin",
            reason="据说有问题",
            contradicting_evidence_ids=[],
        )
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED


async def test_dispute_preserves_both_sides(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed(session, grades=["A"], status="verified")
    counter = await add_evidence(session, make_evidence("A", origin_key="counter-origin"))

    updated = await dispute(
        session,
        rel.id,
        actor="human:kevin",
        reason="客户否认合作",
        contradicting_evidence_ids=[counter.id],
    )

    assert updated.status == "disputed"

    rows = (
        await session.execute(
            select(RelationshipEvidence.relation).where(
                RelationshipEvidence.relationship_id == rel.id
            )
        )
    ).scalars()
    relations = sorted(rows)
    assert relations == ["contradicting", "supporting"], "original evidence must survive"

    history = await _history(session, rel.id)
    assert history[-1].trigger == "new_evidence"
    assert history[-1].evidence_ids == [counter.id]
    assert history[-1].reason == "客户否认合作"


async def test_disputed_cannot_be_verified_while_conflict_stands(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed(session, grades=["A"], status="verified")
    counter = await add_evidence(session, make_evidence("A", origin_key="counter-origin"))
    await dispute(
        session,
        rel.id,
        actor="human:kevin",
        reason="客户否认合作",
        contradicting_evidence_ids=[counter.id],
    )

    with pytest.raises(AppError) as exc:
        await verify(session, rel.id, approved_by="human:kevin")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED
    assert any("contradicting" in r for r in exc.value.details["reasons"])


async def test_conflict_resolution_allows_verification_again(
    session: AsyncSession, clean_db: None
) -> None:
    """Once the contradicting link is withdrawn, the fact can be re-established."""
    rel, _ = await _seed(session, grades=["A"], status="verified")
    counter = await add_evidence(session, make_evidence("A", origin_key="counter-origin"))
    await dispute(
        session,
        rel.id,
        actor="human:kevin",
        reason="客户否认合作",
        contradicting_evidence_ids=[counter.id],
    )

    row = (
        await session.execute(
            select(RelationshipEvidence).where(
                RelationshipEvidence.relationship_id == rel.id,
                RelationshipEvidence.relation == "contradicting",
            )
        )
    ).scalar_one()
    await session.delete(row)
    await session.flush()

    restored = await verify(session, rel.id, approved_by="human:kevin", reason="证据被撤回")
    assert restored.status == "verified"


# ---------------------------------------------------------------------------
# Generic transition guardrails
# ---------------------------------------------------------------------------


async def test_generic_transition_cannot_verify(session: AsyncSession, clean_db: None) -> None:
    """Verification must go through its dedicated entry point, not the generic one."""
    rel, _ = await _seed(session, grades=["A"], status="pending_review")

    with pytest.raises(AppError) as exc:
        await transition(session, rel.id, "verified", actor="human:kevin")
    assert exc.value.code is ErrorCode.VALIDATION_ERROR


async def test_revoke_keeps_row_and_appends_history(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed(session, grades=["A"], status="verified")
    await transition(session, rel.id, "revoked", actor="human:kevin", reason="公告撤回")

    still_there = (
        await session.execute(select(Relationship).where(Relationship.id == rel.id))
    ).scalar_one()
    assert still_there.status == "revoked"

    count = (
        await session.execute(
            select(func.count())
            .select_from(RelationshipHistory)
            .where(RelationshipHistory.relationship_id == rel.id)
        )
    ).scalar_one()
    assert count == 1
