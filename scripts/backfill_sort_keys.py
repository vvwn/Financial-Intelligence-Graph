"""Backfill entity.name_sort_key.

Run after deploying a new sort-key version, or when entities were inserted without
a key (e.g. by raw SQL). Every change is recorded in entity_sort_key_history.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/backfill_sort_keys.py --dry-run
    backend/.venv/Scripts/python.exe scripts/backfill_sort_keys.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.models.entity import Entity, EntitySortKeyHistory  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main(apply: bool) -> int:
    version = sort_key_version()
    factory = get_session_factory()
    changed = 0

    async with factory() as session:
        entities = (await session.execute(select(Entity))).scalars().all()
        for entity in entities:
            new_key = build_sort_key(entity.canonical_name)
            if new_key == entity.name_sort_key and entity.name_sort_key_version == version:
                continue

            changed += 1
            print(
                f"{entity.id} {entity.canonical_name!r}: "
                f"{entity.name_sort_key!r} -> {new_key!r} ({version})"
            )
            if not apply:
                continue

            session.add(
                EntitySortKeyHistory(
                    entity_id=entity.id,
                    old_key=entity.name_sort_key,
                    new_key=new_key,
                    old_version=entity.name_sort_key_version,
                    new_version=version,
                    reason="backfill",
                    actor="script:backfill_sort_keys",
                )
            )
            entity.name_sort_key = new_key
            entity.name_sort_key_version = version

        if apply:
            await session.commit()

    await dispose()
    mode = "applied" if apply else "would change (dry run)"
    print(f"{mode}: {changed} of {len(entities)} entities")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op flag")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(apply=args.apply and not args.dry_run)))
