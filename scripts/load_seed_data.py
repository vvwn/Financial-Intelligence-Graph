"""Load seed data into PostgreSQL.

Two datasets, deliberately kept apart:

* `industries.yaml` — real industry segmentation, no company claims.
* `demo_companies.yaml` — **SYNTHETIC** companies and relationships, used only to
  exercise the pipeline end to end. Every row is marked synthetic; the loader
  refuses to run without an explicit flag and refuses to run in production.

Why synthetic: writing plausible-looking A-share supply relationships with fake
announcements would be exactly the failure mode this project exists to prevent.
Real company data must arrive through the collector with real evidence.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/load_seed_data.py --industries
    backend/.venv/Scripts/python.exe scripts/load_seed_data.py --demo --i-know-this-is-synthetic
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.models.claim import Claim, ClaimRelationship  # noqa: E402
from app.models.entity import Entity, IndustryTaxonomy  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

SEED_DIR = REPO_ROOT / "database" / "seeds"
DEMO_MARKER = "SYNTHETIC-DEMO"


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


async def _upsert_entity(session, row: dict) -> Entity:
    existing = (
        await session.execute(select(Entity).where(Entity.stock_code == row["stock_code"]))
    ).scalar_one_or_none()
    if existing:
        return existing

    entity = Entity(
        entity_type="listed_company",
        canonical_name=row["name"],
        normalized_name=row["name"].strip().lower(),
        name_sort_key=build_sort_key(row["name"]),
        name_sort_key_version=sort_key_version(),
        stock_code=row["stock_code"],
        exchange=row.get("exchange", "SZSE"),
        industry_code=row.get("industry_code"),
        attributes={"synthetic": True, "note": DEMO_MARKER},
    )
    session.add(entity)
    await session.flush()
    return entity


async def load_demo(session) -> dict:
    data = yaml.safe_load((SEED_DIR / "demo_companies.yaml").read_text(encoding="utf-8"))
    stats = {"entities": 0, "evidence": 0, "relationships": 0}

    entities: dict[str, Entity] = {}
    for row in data["companies"]:
        entities[row["key"]] = await _upsert_entity(session, row)
        stats["entities"] += 1

    for row in data["relationships"]:
        source = entities[row["source"]]
        target = entities[row["target"]]

        existing = (
            await session.execute(
                select(Relationship).where(
                    Relationship.source_entity_id == source.id,
                    Relationship.target_entity_id == target.id,
                    Relationship.relationship_type == row["type"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue

        origin_key = f"{DEMO_MARKER}:{row['source']}->{row['target']}:{row['type']}"
        excerpt = row["excerpt"]
        evidence = Evidence(
            source_type="announcement",
            source_name=f"{DEMO_MARKER} 合成样例（非真实公告）",
            source_url=None,
            title=f"[合成数据] {row['source']} → {row['target']}",
            original_excerpt=excerpt,
            collected_at=datetime.now(UTC) - timedelta(days=1),
            evidence_grade=row.get("grade", "A"),
            content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
            origin_key=origin_key,
        )
        session.add(evidence)
        await session.flush()
        stats["evidence"] += 1

        relationship = Relationship(
            source_entity_id=source.id,
            target_entity_id=target.id,
            relationship_type=row["type"],
            status="verified",
            confidence=row.get("confidence", 0.8),
            last_verified_at=datetime.now(UTC),
            attributes={"synthetic": True},
        )
        session.add(relationship)
        await session.flush()

        claim = Claim(
            subject_entity_id=source.id,
            predicate=row["type"],
            object_entity_id=target.id,
            claim_type="fact_reported",
            confidence=0.8,
            status="supported",
        )
        session.add(claim)
        await session.flush()

        session.add(ClaimRelationship(claim_id=claim.id, relationship_id=relationship.id))
        session.add(
            RelationshipEvidence(
                relationship_id=relationship.id,
                evidence_id=evidence.id,
                relation="supporting",
            )
        )
        stats["relationships"] += 1

    await session.commit()
    return stats


async def main(args: argparse.Namespace) -> int:
    if args.demo and not args.i_know_this_is_synthetic:
        print(
            "refusing to load synthetic demo data without --i-know-this-is-synthetic",
            file=sys.stderr,
        )
        return 2
    if args.demo and settings.is_production:
        print("refusing to load synthetic demo data in production", file=sys.stderr)
        return 2

    factory = get_session_factory()
    async with factory() as session:
        if args.industries or args.demo:
            created = await load_industries(session)
            print(f"industries: {created} created")
        if args.demo:
            stats = await load_demo(session)
            print(
                f"demo: entities={stats['entities']} evidence={stats['evidence']} "
                f"relationships={stats['relationships']}"
            )

    await dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--industries", action="store_true", help="load industry taxonomy")
    parser.add_argument("--demo", action="store_true", help="load synthetic demo companies")
    parser.add_argument(
        "--i-know-this-is-synthetic",
        action="store_true",
        dest="i_know_this_is_synthetic",
        help="required acknowledgement for --demo",
    )
    raise SystemExit(asyncio.run(main(parser.parse_args())))
