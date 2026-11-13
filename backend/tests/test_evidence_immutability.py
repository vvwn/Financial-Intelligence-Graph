"""I-5: evidence rows are immutable at the database level.

Both directions are tested: legal corrections must work, illegal mutations must fail.
A guard that blocks everything is as broken as one that blocks nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.models.evidence import Evidence
from factories import add_evidence, make_evidence
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.db


async def _one_evidence(session: AsyncSession, **kwargs) -> Evidence:
    return await add_evidence(session, make_evidence("A", **kwargs))


# ---------------------------------------------------------------------------
# Illegal mutations must be refused
# ---------------------------------------------------------------------------


async def test_update_excerpt_is_refused(session: AsyncSession, clean_db: None) -> None:
    ev = await _one_evidence(session)
    await session.commit()

    with pytest.raises(DBAPIError) as exc:
        await session.execute(
            text("UPDATE evidence SET original_excerpt = '改过的原文' WHERE id = :id"),
            {"id": ev.id},
        )
        await session.commit()
    assert "immutable" in str(exc.value).lower()
    await session.rollback()


async def test_update_grade_is_refused(session: AsyncSession, clean_db: None) -> None:
    """Upgrading a C to an A would launder weak evidence into strong; it must fail."""
    ev = await add_evidence(session, make_evidence("C"))
    await session.commit()

    with pytest.raises(DBAPIError):
        await session.execute(
            text("UPDATE evidence SET evidence_grade = 'A' WHERE id = :id"), {"id": ev.id}
        )
        await session.commit()
    await session.rollback()


async def test_delete_is_refused(session: AsyncSession, clean_db: None) -> None:
    ev = await _one_evidence(session)
    await session.commit()

    with pytest.raises(DBAPIError) as exc:
        await session.execute(text("DELETE FROM evidence WHERE id = :id"), {"id": ev.id})
        await session.commit()
    assert "append-only" in str(exc.value).lower()
    await session.rollback()


async def test_cannot_clear_supersedes_link(session: AsyncSession, clean_db: None) -> None:
    origin = uuid.uuid4().hex
    old = await _one_evidence(session, origin_key=origin)
    await session.commit()

    new = make_evidence("A", origin_key=origin)
    new.supersedes_id = old.id
    new.collected_at = old.collected_at + timedelta(hours=1)
    await add_evidence(session, new)
    await session.commit()

    with pytest.raises(DBAPIError):
        await session.execute(
            text("UPDATE evidence SET supersedes_id = NULL WHERE id = :id"), {"id": new.id}
        )
        await session.commit()
    await session.rollback()


# ---------------------------------------------------------------------------
# Legal paths must work
# ---------------------------------------------------------------------------


async def test_verification_status_may_change(session: AsyncSession, clean_db: None) -> None:
    """Reviewing evidence is legitimate; rewriting its content is not."""
    ev = await _one_evidence(session)
    await session.commit()

    await session.execute(
        text("UPDATE evidence SET verification_status = 'verified' WHERE id = :id"),
        {"id": ev.id},
    )
    await session.commit()

    # Read the column directly: the ORM instance keeps its stale attribute after a
    # raw UPDATE (expire_on_commit=False), and expiring it would trigger a lazy
    # load outside the async context.
    status = (
        await session.execute(
            text("SELECT verification_status FROM evidence WHERE id = :id"), {"id": ev.id}
        )
    ).scalar_one()
    assert status == "verified"


async def test_correction_via_new_row_is_allowed(session: AsyncSession, clean_db: None) -> None:
    """The sanctioned fix: append a new row that supersedes the old one."""
    origin = uuid.uuid4().hex
    old = await _one_evidence(session, origin_key=origin)
    await session.commit()

    corrected = make_evidence("A", origin_key=origin)
    corrected.original_excerpt = "更正后的原文"
    corrected.supersedes_id = old.id
    corrected.collected_at = old.collected_at + timedelta(minutes=5)
    await add_evidence(session, corrected)
    await session.commit()

    rows = (await session.execute(select(Evidence))).scalars().all()
    assert len(rows) == 2
    superseding = [r for r in rows if r.supersedes_id == old.id]
    assert len(superseding) == 1
    assert superseding[0].original_excerpt == "更正后的原文"


async def test_repost_may_share_origin(session: AsyncSession, clean_db: None) -> None:
    origin = uuid.uuid4().hex
    first = await _one_evidence(session, origin_key=origin)
    await session.commit()

    repost = make_evidence("C", origin_key=origin, source_name="转载媒体")
    repost.syndicated_from_id = first.id
    await add_evidence(session, repost)
    await session.commit()

    rows = (await session.execute(select(Evidence))).scalars().all()
    assert len(rows) == 2
    assert {r.origin_key for r in rows} == {origin}


# ---------------------------------------------------------------------------
# Linkage guardrails (controlled append)
# ---------------------------------------------------------------------------


async def test_supersedes_with_different_origin_is_refused(
    session: AsyncSession, clean_db: None
) -> None:
    old = await _one_evidence(session, origin_key="origin-1")
    await session.commit()

    wrong = make_evidence("A", origin_key="origin-2")
    wrong.supersedes_id = old.id
    wrong.collected_at = datetime.now(UTC) + timedelta(minutes=1)

    with pytest.raises(DBAPIError) as exc:
        await add_evidence(session, wrong)
        await session.commit()
    assert "origin_key" in str(exc.value)
    await session.rollback()


async def test_supersedes_missing_row_is_refused(session: AsyncSession, clean_db: None) -> None:
    orphan = make_evidence("A", origin_key="origin-3")
    orphan.supersedes_id = uuid.uuid4()

    with pytest.raises(DBAPIError):
        await add_evidence(session, orphan)
        await session.commit()
    await session.rollback()


async def test_superseding_row_cannot_predate_the_original(
    session: AsyncSession, clean_db: None
) -> None:
    origin = uuid.uuid4().hex
    old = await _one_evidence(session, origin_key=origin)
    await session.commit()

    earlier = make_evidence("A", origin_key=origin)
    earlier.supersedes_id = old.id
    earlier.collected_at = old.collected_at - timedelta(days=1)

    with pytest.raises(DBAPIError) as exc:
        await add_evidence(session, earlier)
        await session.commit()
    assert "predate" in str(exc.value)
    await session.rollback()
