"""Live-DB verification of the invariants that Phase 0 claims to enforce.

Why a separate script instead of relying on pytest alone:
the tests use the ORM, which could in principle be the thing doing the blocking.
This script talks to PostgreSQL with raw SQL, inside a transaction that is always
rolled back — so evidence rows (which cannot be deleted) do not accumulate.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/verify_invariants.py
Exit code 0 = every invariant holds; 1 = at least one FAIL.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_engine  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.validation.state_guard import (  # noqa: E402
    EvidenceFact,
    assert_usable_for_propagation,
    evaluate_threshold,
    evaluate_verification,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<44} {detail}")


def uid() -> str:
    return str(uuid.uuid4())


async def expect_db_error(conn, label: str, sql: str, params: dict | None = None) -> None:
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql), params or {})
        record(label, False, "no error raised — the guard is missing")
    except DBAPIError as exc:
        msg = str(exc.orig).split("\n")[0][:80]
        record(label, True, msg)


async def expect_db_ok(conn, label: str, sql: str, params: dict | None = None) -> None:
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql), params or {})
        record(label, True, "allowed as intended")
    except DBAPIError as exc:
        record(label, False, str(exc.orig).split("\n")[0][:80])


async def main() -> int:
    engine = get_engine()
    now = datetime.now(UTC)

    async with engine.connect() as conn:
        outer = await conn.begin()

        entity_a, entity_b = uid(), uid()
        for eid, name, code in (
            (entity_a, "不变量核验甲", "910001"),
            (entity_b, "不变量核验乙", "910002"),
        ):
            await conn.execute(
                text(
                    """INSERT INTO entity
                       (id, entity_type, canonical_name, normalized_name, name_sort_key,
                        name_sort_key_version, stock_code, attributes, status)
                       VALUES (:id, 'listed_company', :n, :n, :k, :v, :c, '{}'::jsonb, 'active')"""
                ),
                {"id": eid, "n": name, "k": build_sort_key(name), "v": sort_key_version(), "c": code},
            )

        print("\n--- I-5 证据不可变（裸 SQL 直接撞触发器）---")

        ev_origin = uid()
        ev_id = uid()
        await conn.execute(
            text(
                """INSERT INTO evidence
                   (id, source_type, source_name, original_excerpt, collected_at,
                    evidence_grade, content_hash, origin_key, verification_status)
                   VALUES (:id, 'announcement', '核验源', '原始正文', :t, 'C', :h, :o, 'unverified')"""
            ),
            {"id": ev_id, "t": now, "h": uid(), "o": ev_origin},
        )

        await expect_db_error(
            conn,
            "I-5 改正文被拒",
            "UPDATE evidence SET original_excerpt = '被篡改' WHERE id = :id",
            {"id": ev_id},
        )
        await expect_db_error(
            conn,
            "I-5 改等级被拒",
            "UPDATE evidence SET evidence_grade = 'A' WHERE id = :id",
            {"id": ev_id},
        )
        await expect_db_error(
            conn,
            "I-5 改来源被拒",
            "UPDATE evidence SET source_name = '伪造来源' WHERE id = :id",
            {"id": ev_id},
        )
        await expect_db_error(conn, "I-5 物理删除被拒", "DELETE FROM evidence WHERE id = :id", {"id": ev_id})
        await expect_db_ok(
            conn,
            "I-5 改复核状态允许",
            "UPDATE evidence SET verification_status = 'verified' WHERE id = :id",
            {"id": ev_id},
        )

        corrected = uid()
        await expect_db_ok(
            conn,
            "I-5 追加式修正允许（同源）",
            """INSERT INTO evidence
               (id, source_type, source_name, original_excerpt, collected_at,
                evidence_grade, content_hash, origin_key, supersedes_id, verification_status)
               VALUES (:id, 'announcement', '核验源', '更正后正文', :t, 'C', :h, :o, :sup, 'unverified')""",
            {"id": corrected, "t": now + timedelta(minutes=1), "h": uid(), "o": ev_origin, "sup": ev_id},
        )
        await expect_db_error(
            conn,
            "I-5 异源 supersedes 被拒",
            """INSERT INTO evidence
               (id, source_type, source_name, original_excerpt, collected_at,
                evidence_grade, content_hash, origin_key, supersedes_id, verification_status)
               VALUES (:id, 'announcement', '核验源', '另一来源', :t, 'C', :h, :o, :sup, 'unverified')""",
            {"id": uid(), "t": now, "h": uid(), "o": uid(), "sup": ev_id},
        )
        await expect_db_error(
            conn,
            "I-5 倒序 supersedes 被拒",
            """INSERT INTO evidence
               (id, source_type, source_name, original_excerpt, collected_at,
                evidence_grade, content_hash, origin_key, supersedes_id, verification_status)
               VALUES (:id, 'announcement', '核验源', '早于原件', :t, 'C', :h, :o, :sup, 'unverified')""",
            {"id": uid(), "t": now - timedelta(days=1), "h": uid(), "o": ev_origin, "sup": ev_id},
        )

        print("\n--- I-6 独立性：同源转载只算 1 个来源 ---")
        same_origin = [EvidenceFact(evidence_id=uid(), grade="C", origin_key="one-origin") for _ in range(5)]
        d_same = evaluate_threshold("fact_reported", same_origin)
        record(
            "I-6 5 条同源 C 级不算达标",
            (not d_same.met) and d_same.distinct_supporting_origins == 1,
            f"origins={d_same.distinct_supporting_origins} met={d_same.met}",
        )
        diff_origin = [
            EvidenceFact(evidence_id=uid(), grade="C", origin_key="origin-a"),
            EvidenceFact(evidence_id=uid(), grade="C", origin_key="origin-b"),
        ]
        d_diff = evaluate_threshold("fact_reported", diff_origin)
        record(
            "I-6 2 条异源 C 级达标",
            d_diff.met and d_diff.distinct_supporting_origins == 2,
            f"origins={d_diff.distinct_supporting_origins} met={d_diff.met}",
        )

        print("\n--- I-11 阈值不得自动验证 ---")
        strong = [EvidenceFact(evidence_id=uid(), grade="A", origin_key="o1")]
        no_approval = evaluate_verification("fact_reported", strong, approved_by=None)
        record("I-11 无批准不得 verified", not no_approval.allowed, no_approval.reasons[-1][:60])
        auto = evaluate_verification("fact_reported", strong, approved_by="system:pipeline")
        record("I-11 自动化 actor 不得批准", not auto.allowed, auto.reasons[-1][:60])
        human = evaluate_verification("fact_reported", strong, approved_by="human:kevin")
        record("I-11 人工批准可 verified", human.allowed, "allowed")

        print("\n--- I-12 disputed 必须带反向证据（DB CHECK）---")
        rel_id = uid()
        await conn.execute(
            text(
                """INSERT INTO relationship
                   (id, source_entity_id, target_entity_id, relationship_type, status,
                    confidence, attributes, version)
                   VALUES (:id, :s, :t, 'supplies_to', 'verified', 0.9, '{}'::jsonb, 1)"""
            ),
            {"id": rel_id, "s": entity_a, "t": entity_b},
        )
        await expect_db_error(
            conn,
            "I-12 空证据进 disputed 被拒",
            """INSERT INTO relationship_history
               (id, relationship_id, from_status, to_status, actor, trigger, reason,
                evidence_ids, snapshot)
               VALUES (:id, :r, 'verified', 'disputed', 'human:kevin', 'new_evidence',
                       '无证据', '{}'::uuid[], '{}'::jsonb)""",
            {"id": uid(), "r": rel_id},
        )
        await expect_db_ok(
            conn,
            "I-12 带反向证据进 disputed 允许",
            """INSERT INTO relationship_history
               (id, relationship_id, from_status, to_status, actor, trigger, reason,
                evidence_ids, snapshot)
               VALUES (:id, :r, 'verified', 'disputed', 'human:kevin', 'new_evidence',
                       '客户否认', ARRAY[:e]::uuid[], '{}'::jsonb)""",
            {"id": uid(), "r": rel_id, "e": ev_id},
        )

        print("\n--- I-13 disputed 不得用于传导 ---")
        try:
            assert_usable_for_propagation("disputed")
            record("I-13 disputed 阻断传导", False, "no error raised")
        except AppError as exc:
            record("I-13 disputed 阻断传导", True, exc.code.value)
        try:
            assert_usable_for_propagation("verified")
            record("I-13 verified 允许传导", True, "allowed")
        except AppError as exc:  # pragma: no cover
            record("I-13 verified 允许传导", False, exc.code.value)

        print("\n--- I-4 历史只追加（裸 SQL）---")
        await expect_db_error(
            conn,
            "I-4 改历史被拒",
            "UPDATE relationship_history SET actor = 'tampered' WHERE relationship_id = :r",
            {"r": rel_id},
        )
        await expect_db_error(
            conn,
            "I-4 删历史被拒",
            "DELETE FROM relationship_history WHERE relationship_id = :r",
            {"r": rel_id},
        )

        # Everything above is undone: evidence rows cannot be deleted, so the whole
        # transaction is rolled back rather than cleaned up row by row.
        await outer.rollback()

    await dispose()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f"\n===== {passed} passed, {failed} failed =====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
