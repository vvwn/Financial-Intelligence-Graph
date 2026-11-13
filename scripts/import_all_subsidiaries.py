"""Import subsidiaries for every company in the AI-compute universe.

Runs the annual-report pipeline across the whole universe, one company at a time,
and writes a summary table so failures are visible instead of silently skipped.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_all_subsidiaries.py --dry-run
    backend/.venv/Scripts/python.exe scripts/import_all_subsidiaries.py --apply
    backend/.venv/Scripts/python.exe scripts/import_all_subsidiaries.py --apply --only 300308,300502
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.models.relationship import Relationship  # noqa: E402
from app.services.annual_report_import import (  # noqa: E402
    SubsidiaryImportResult,
    import_for_code,
)
from sqlalchemy import func, select  # noqa: E402

UNIVERSE = REPO_ROOT / "database" / "seeds" / "ai_compute_universe.yaml"


async def main(apply: bool, only: set[str] | None) -> int:
    data = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    codes = [e["code"].split(".")[-1] for e in data["companies"]]
    if only:
        codes = [c for c in codes if c in only]

    print(f"universe: {len(codes)} companies | mode={'apply' if apply else 'dry-run'}")
    print(f"{'code':<8} {'report':<28} {'parsed':>7} {'created':>8}  note")
    print("-" * 86)

    factory = get_session_factory()
    ok = failed = total_created = 0
    failures: list[tuple[str, str]] = []
    started = time.time()

    async with factory() as session:
        for index, code in enumerate(codes, 1):
            try:
                result = await import_for_code(session, code)
            except Exception as exc:  # noqa: BLE001 - one bad company must not abort the batch
                await session.rollback()
                result = SubsidiaryImportResult(
                    code=code, ok=False, error=f"{type(exc).__name__}: {str(exc)[:90]}"
                )
            if apply and result.ok:
                await session.commit()
            else:
                await session.rollback()

            title = (result.report_title or "-")[:26]
            note = "" if result.ok else (result.error or "unknown")
            print(
                f"{code:<8} {title:<28} {result.parsed:>7} {result.created:>8}  {note}",
                flush=True,
            )

            if result.ok:
                ok += 1
                total_created += result.created
            else:
                failed += 1
                failures.append((code, result.error or "unknown"))

            if index % 10 == 0:
                print(f"  ... {index}/{len(codes)} done, {time.time() - started:.0f}s", flush=True)

    # Post-run sanity: how many subsidiary edges exist in total.
    async with factory() as session:
        total_edges = (
            await session.execute(
                select(func.count())
                .select_from(Relationship)
                .where(Relationship.relationship_type.in_(["controls", "holds_stake_in"]))
            )
        ).scalar_one()

    await dispose()

    print("-" * 86)
    print(f"succeeded: {ok}  failed: {failed}  edges created: {total_created}")
    print(f"total equity edges in database: {total_edges}")
    print(f"elapsed: {time.time() - started:.0f}s")
    if failures:
        print("\nfailures:")
        for code, reason in failures:
            print(f"  {code}: {reason}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="comma separated stock codes")
    args = parser.parse_args()
    only = {c.strip() for c in args.only.split(",")} if args.only else None
    raise SystemExit(asyncio.run(main(apply=args.apply and not args.dry_run, only=only)))
