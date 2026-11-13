"""Load the industry taxonomy into PostgreSQL.

Company data is NOT seeded here. It comes from a real source via
`scripts/import_baostock_universe.py`; the synthetic demo dataset was removed once
the Baostock path worked (2026-11-13).

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/load_seed_data.py --industries
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.models.entity import IndustryTaxonomy  # noqa: E402

SEED_DIR = REPO_ROOT / "database" / "seeds"


async def load_industries(session) -> int:
    data = yaml.safe_load((SEED_DIR / "industries.yaml").read_text(encoding="utf-8"))
    created = 0
    for row in data["industries"]:
        existing = await session.get(IndustryTaxonomy, row["code"])
        if existing is None:
            session.add(
                IndustryTaxonomy(
                    code=row["code"],
                    name=row["name"],
                    parent_code=row.get("parent_code"),
                    level=row["level"],
                    description=row.get("description"),
                )
            )
            created += 1
        else:
            existing.name = row["name"]
            existing.parent_code = row.get("parent_code")
            existing.level = row["level"]
            existing.description = row.get("description")
    await session.commit()
    return created


async def main(args: argparse.Namespace) -> int:
    factory = get_session_factory()
    async with factory() as session:
        created = await load_industries(session)
        print(f"industries: {created} created")

    await dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--industries", action="store_true", help="load industry taxonomy")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
