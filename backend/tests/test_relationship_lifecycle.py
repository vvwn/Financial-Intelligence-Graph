"""Integration tests: guards actually hold against a live PostgreSQL.

These are the tests that prove invariants are enforced by code and DB
constraints, not merely promised in docs.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7
from app.models.claim import Claim
from app.models.relationship import Relationship, RelationshipHistory
from app.services.relationship_service import transition
from factories import (
    link_claim,
    link_evidence,
    make_claim,
    make_entity,
    make_evidence,
    make_relationship,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db


_CODE_SEQ = {"n": 0}


def _next_code() -> str:
    """Six-digit stock codes must be unique per test; reuse breaks the unique index."""
    _CODE_SEQ["n"] += 1
    return f"{600000 + _CODE_SEQ['n']:06d}"


async def _seed_promotable(
    session: AsyncSession, grades: list[str], claim_type: str = "fact_reported"
) -> tuple[Relationship, Claim]:
    supplier = await make_entity(session, f"示例光模块股份{_next_code()}", _next_code())
    customer = await make_entity(session, f"示例云科技{_next_code()}", _next_code())
    rel = await make_relationship(session, supplier, customer, status="pending_review")
    claim = await make_claim(session, supplier, customer, claim_type=claim_type)
    await link_claim(session, claim, rel)
    for grade in grades:
        ev = await make_evidence(session, grade)
        await link_evidence(session, rel, ev, claim)
    return rel, claim


# ---------------------------------------------------------------------------
# Happy path and provenance
# ---------------------------------------------------------------------------


async def test_pending_review_to_verified_with_grade_a(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed_promotable(session, ["A"])

    updated = await transition(session, rel.id, "verified", actor="qa-audit", reason="公告核对")

    assert updated.status == "verified"
    assert updated.version == 2
    assert updated.last_verified_at is not None

    history = (
        await session.execute(
            select(RelationshipHistory).where(RelationshipHistory.relationship_id == rel.id)
        )
    ).scalar_one()
    assert history.from_status == "pending_review"
    assert history.to_status == "verified"
    assert history.actor == "qa-audit"
    assert history.snapshot["status"] == "verified"


async def test_no_claim_means_no_verification(session: AsyncSession, clean_db: None) -> None:
    """Provenance is mandatory: evidence without a claim cannot be verified."""
    supplier = await make_entity(session, "无来源股份", "300011")
    customer = await make_entity(session, "无来源客户", "300012")
    rel = await make_relationship(session, supplier, customer, status="pending_review")
    ev = await make_evidence(session, "A")
    await link_evidence(session, rel, ev)

    with pytest.raises(AppError) as exc:
        await transition(session, rel.id, "verified", actor="qa-audit")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED


async def test_inferred_claim_blocked_at_service_layer(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed_promotable(session, ["A"], claim_type="inferred")

    with pytest.raises(AppError) as exc:
        await transition(session, rel.id, "verified", actor="qa-audit")
    assert exc.value.code is ErrorCode.CLAIM_TYPE_NOT_PROMOTABLE
    assert rel.status == "pending_review"


async def test_single_grade_c_rejected_two_accepted(
    session: AsyncSession, clean_db: None
) -> None:
    rel_one, _ = await _seed_promotable(session, ["C"])
    with pytest.raises(AppError) as exc:
        await transition(session, rel_one.id, "verified", actor="qa-audit")
    assert exc.value.code is ErrorCode.EVIDENCE_REQUIRED

    rel_two, _ = await _seed_promotable(session, ["C", "C"])
    updated = await transition(session, rel_two.id, "verified", actor="qa-audit")
    assert updated.status == "verified"


async def test_illegal_transition_blocked(session: AsyncSession, clean_db: None) -> None:
    """verified -> candidate must be impossible through the service."""
    rel, _ = await _seed_promotable(session, ["A"])
    await transition(session, rel.id, "verified", actor="qa-audit")

    with pytest.raises(AppError) as exc:
        await transition(session, rel.id, "candidate", actor="qa-audit")
    assert exc.value.code is ErrorCode.STATE_TRANSITION_INVALID


async def test_revoke_keeps_the_row_and_appends_history(
    session: AsyncSession, clean_db: None
) -> None:
    rel, _ = await _seed_promotable(session, ["A"])
    await transition(session, rel.id, "verified", actor="qa-audit")
    await transition(session, rel.id, "revoked", actor="kevin", reason="公告撤回")

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
    assert count == 2


async def test_transition_is_idempotent(session: AsyncSession, clean_db: None) -> None:
    rel, _ = await _seed_promotable(session, ["A"])
    await transition(session, rel.id, "verified", actor="qa-audit")
    again = await transition(session, rel.id, "verified", actor="qa-audit")
    assert again.version == 2


# ---------------------------------------------------------------------------
# DB-level invariants
# ---------------------------------------------------------------------------


async def test_history_is_append_only(session: AsyncSession, clean_db: None) -> None:
    """I-4: the trigger must refuse UPDATE on relationship_history."""
    rel, _ = await _seed_promotable(session, ["A"])
    await transition(session, rel.id, "verified", actor="qa-audit")
    await session.commit()

    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE relationship_history SET actor = 'tampered'"))
        await session.commit()
    await session.rollback()


async def test_duplicate_active_triple_rejected(session: AsyncSession, clean_db: None) -> None:
    supplier = await make_entity(session, "重复股份", "300021")
    customer = await make_entity(session, "重复客户", "300022")
    await make_relationship(session, supplier, customer, status="verified")
    await session.commit()

    session.add(
        Relationship(
            id=uuid7(),
            source_entity_id=supplier.id,
            target_entity_id=customer.id,
            relationship_type="supplies_to",
            status="pending_review",
            confidence=0.5,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_self_loop_rejected(session: AsyncSession, clean_db: None) -> None:
    entity = await make_entity(session, "自环股份", "300031")
    session.add(
        Relationship(
            id=uuid7(),
            source_entity_id=entity.id,
            target_entity_id=entity.id,
            relationship_type="supplies_to",
            status="candidate",
            confidence=0.5,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_confidence_above_one_rejected(session: AsyncSession, clean_db: None) -> None:
    supplier = await make_entity(session, "越界股份", "300041")
    customer = await make_entity(session, "越界客户", "300042")
    session.add(
        Relationship(
            id=uuid7(),
            source_entity_id=supplier.id,
            target_entity_id=customer.id,
            relationship_type="supplies_to",
            status="candidate",
            confidence=1.5,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_inferred_claim_confidence_capped_in_db(
    session: AsyncSession, clean_db: None
) -> None:
    """The DB CHECK mirrors the Python guard, so raw SQL cannot bypass it either."""
    supplier = await make_entity(session, "推断股份", "300051")
    customer = await make_entity(session, "推断客户", "300052")
    session.add(
        Claim(
            id=uuid7(),
            subject_entity_id=supplier.id,
            predicate="supplies_to",
            object_entity_id=customer.id,
            claim_type="inferred",
            confidence=0.9,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_evidence_view_dedupes_reposts(session: AsyncSession, clean_db: None) -> None:
    """I-6 view: five reposts of one article collapse to a single row."""
    same_hash = uuid.uuid4().hex
    for _ in range(5):
        ev = await make_evidence(session, "C", content_hash=same_hash)
        session.add(ev)
    await session.commit()

    rows = (
        await session.execute(
            text("SELECT count(*) AS n, max(repost_count) AS r FROM v_evidence_distinct")
        )
    ).one()
    assert rows.n == 1
    assert rows.r == 5
