"""Import named supply-chain edges extracted from related-party announcements.

Each entry in `related_party_edges.yaml` carries the announcement URL and the
verbatim excerpt it was extracted from, so the edge can be checked against the
original PDF. Entities are created on demand; the relationships are verified
because the announcement is grade-A evidence.

This is a template for the Phase 2 collector, not a bulk importer: the YAML is
curated by hand, and the volume it can reach is bounded by how many companies
disclose named counterparties at all.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_related_party_edges.py --dry-run
    backend/.venv/Scripts/python.exe scripts/import_related_party_edges.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.models.claim import Claim, ClaimRelationship  # noqa: E402
from app.models.entity import Entity, EntityAlias  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

SEED = REPO_ROOT / "database" / "seeds" / "related_party_edges.yaml"


async def _entity(session, spec: dict) -> Entity:
    stock_code = spec.get("stock_code")
    stmt = select(Entity)
    stmt = (
        stmt.where(Entity.stock_code == stock_code)
        if stock_code
        else stmt.where(Entity.canonical_name == spec["name"])
    )
    entity = (await session.execute(stmt)).scalar_one_or_none()
    if entity is None:
        entity = Entity(
            entity_type=spec["entity_type"],
            canonical_name=spec["name"],
            normalized_name=spec["name"].strip().lower(),
            name_sort_key=build_sort_key(spec["name"]),
            name_sort_key_version=sort_key_version(),
            stock_code=stock_code,
            exchange=spec.get("exchange"),
            industry_code=spec.get("industry_code"),
            attributes={"data_source": "cninfo_related_party_announcement"},
        )
        session.add(entity)
        await session.flush()

    for alias in spec.get("aliases", []):
        exists = (
            await session.execute(
                select(EntityAlias).where(
                    EntityAlias.entity_id == entity.id, EntityAlias.alias == alias
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                EntityAlias(entity_id=entity.id, alias=alias, alias_type="abbr")
            )
    await session.flush()
    return entity


async def import_edges(apply: bool) -> int:
    data = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    created = 0

    factory = get_session_factory()
    async with factory() as session:
        for block in data["edges"]:
            excerpt = block["excerpt"].strip()
            print(f"\n[{block['id']}] {block['announcement_title'][:44]}...")

            if not apply:
                for rel in block["relationships"]:
                    print(
                        f"  would create {rel['source']} -{rel['type']}-> {rel['target']} "
                        f"(conf {rel['confidence']})"
                    )
                continue

            entities = {}
            for spec in block["entities"]:
                entities[spec["key"]] = await _entity(session, spec)

            evidence = Evidence(
                source_type="announcement",
                source_name="巨潮资讯网 · 上市公司公告",
                source_url=block["source_url"],
                title=block["announcement_title"],
                original_excerpt=excerpt,
                published_at=datetime.fromisoformat(block["announcement_date"]).replace(tzinfo=UTC),
                collected_at=datetime.now(UTC),
                evidence_grade=block["evidence_grade"],
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                origin_key=f"cninfo:{block['source_url'].rsplit('/', 1)[-1]}",
            )
            session.add(evidence)
            await session.flush()

            for rel in block["relationships"]:
                source = entities[rel["source"]]
                target = entities[rel["target"]]

                existing = (
                    await session.execute(
                        select(Relationship).where(
                            Relationship.source_entity_id == source.id,
                            Relationship.target_entity_id == target.id,
                            Relationship.relationship_type == rel["type"],
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    print(f"  skip {rel['type']}: already present")
                    continue

                relationship = Relationship(
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relationship_type=rel["type"],
                    status="verified",
                    confidence=rel["confidence"],
                    valid_from=(
                        datetime.fromisoformat(rel["valid_from"]).replace(tzinfo=UTC)
                        if rel.get("valid_from")
                        else None
                    ),
                    valid_to=(
                        datetime.fromisoformat(rel["valid_to"]).replace(tzinfo=UTC)
                        if rel.get("valid_to")
                        else None
                    ),
                    last_verified_at=datetime.now(UTC),
                    attributes={
                        "evidence_source": "cninfo_announcement",
                        "note": rel.get("note"),
                        "extraction": "manual_curated",
                    },
                )
                session.add(relationship)
                await session.flush()

                claim = Claim(
                    subject_entity_id=source.id,
                    predicate=rel["type"],
                    object_entity_id=target.id,
                    claim_type="fact_reported",
                    confidence=rel["confidence"],
                    status="supported",
                )
                session.add(claim)
                await session.flush()

                session.add(
                    ClaimRelationship(claim_id=claim.id, relationship_id=relationship.id)
                )
                session.add(
                    RelationshipEvidence(
                        relationship_id=relationship.id,
                        evidence_id=evidence.id,
                        relation="supporting",
                    )
                )
                created += 1
                print(f"  created {rel['type']}")

        if apply:
            await session.commit()

    await dispose()
    print(f"\nedges created: {created}" if apply else "\ndry run: nothing written")
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(import_edges(apply=args.apply and not args.dry_run)) and 0
    )
