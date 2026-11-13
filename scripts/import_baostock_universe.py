"""Import the AI-compute universe from Baostock.

What this produces:
  * real listed-company entities (name / IPO date / CSRC industry from Baostock)
  * industry entities for the taxonomy
  * `belongs_to_industry` relationships, explicitly marked as a PROJECT
    CLASSIFICATION, not as an extracted fact

What it cannot produce: supply-chain relationships. Baostock has no
customer/supplier data, so no `supplies_to` / `upstream_of` edge is created here.
Those need announcements or research reports (Phase 2 collector).

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_baostock_universe.py --dry-run
    backend/.venv/Scripts/python.exe scripts/import_baostock_universe.py --apply
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

from app.collectors.baostock_collector import SOURCE_KEY, StockFact, fetch_stock_facts  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.models.claim import Claim, ClaimRelationship  # noqa: E402
from app.models.entity import Entity, IndustryTaxonomy  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.news import Source  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

UNIVERSE = REPO_ROOT / "database" / "seeds" / "ai_compute_universe.yaml"


async def _ensure_source(session) -> Source:
    existing = (
        await session.execute(select(Source).where(Source.source_key == SOURCE_KEY))
    ).scalar_one_or_none()
    if existing:
        return existing
    source = Source(
        source_key=SOURCE_KEY,
        name="Baostock 证券宝",
        kind="manual",
        base_url="http://baostock.com",
        license_note="免费公开数据接口；仅提供公司基础信息与证监会行业分类，不含供应链关系",
        enabled=True,
        fetch_interval_seconds=86400,
        last_fetched_at=datetime.now(UTC),
        last_status="succeeded",
    )
    session.add(source)
    await session.flush()
    return source


async def _ensure_industry_entities(session) -> dict[str, Entity]:
    """Industry nodes must exist as entities so `belongs_to_industry` can be projected."""
    rows = list((await session.execute(select(IndustryTaxonomy))).scalars().all())
    out: dict[str, Entity] = {}
    for row in rows:
        entity = (
            await session.execute(
                select(Entity).where(
                    Entity.entity_type == "industry", Entity.industry_code == row.code
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = Entity(
                entity_type="industry",
                canonical_name=row.name,
                normalized_name=row.name.strip().lower(),
                name_sort_key=build_sort_key(row.name),
                name_sort_key_version=sort_key_version(),
                # An industry node does not "belong to" itself: leaving industry_code
                # empty keeps `?industry_code=X` returning companies only.
                industry_code=None,
                attributes={
                    "code": row.code,
                    "level": row.level,
                    "parent_code": row.parent_code,
                },
            )
            session.add(entity)
            await session.flush()
        else:
            # Existing rows may carry the old self-referential industry_code.
            entity.industry_code = None
            entity.attributes = {
                "code": row.code,
                "level": row.level,
                "parent_code": row.parent_code,
            }
        out[row.code] = entity
    return out


async def _upsert_company(session, fact: StockFact, segment: str, rationale: str) -> Entity:
    entity = (
        await session.execute(select(Entity).where(Entity.stock_code == fact.stock_code))
    ).scalar_one_or_none()
    attributes = {
        "data_source": SOURCE_KEY,
        "baostock_code": fact.code,
        "ipo_date": fact.ipo_date,
        "list_status": fact.status,
        "csrc_industry": fact.csrc_industry,
        "segment_rationale": rationale,
        "synthetic": False,
    }
    if entity is None:
        entity = Entity(
            entity_type="listed_company",
            canonical_name=fact.name,
            normalized_name=fact.name.strip().lower(),
            name_sort_key=build_sort_key(fact.name),
            name_sort_key_version=sort_key_version(),
            stock_code=fact.stock_code,
            exchange=fact.exchange,
            industry_code=segment,
            attributes=attributes,
        )
        session.add(entity)
        await session.flush()
    else:
        entity.canonical_name = fact.name
        entity.normalized_name = fact.name.strip().lower()
        entity.name_sort_key = build_sort_key(fact.name)
        entity.exchange = fact.exchange
        entity.industry_code = segment
        entity.attributes = {**(entity.attributes or {}), **attributes}
        await session.flush()
    return entity


async def _link_industry(
    session, company: Entity, industry: Entity, fact: StockFact, rationale: str
) -> bool:
    """Create a project-classification edge, clearly labelled as such."""
    existing = (
        await session.execute(
            select(Relationship).where(
                Relationship.source_entity_id == company.id,
                Relationship.target_entity_id == industry.id,
                Relationship.relationship_type == "belongs_to_industry",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    excerpt = (
        f"[Baostock 证监会行业分类] {fact.name}({fact.code}) 归属 "
        f"{fact.csrc_industry or '未分类'}；本项目产业划分：{industry.canonical_name}。"
        f"划分依据：{rationale}"
    )
    evidence = Evidence(
        source_type="research_report",
        source_name="Baostock 证监会行业分类（数据商转载）",
        source_url="http://baostock.com",
        title=f"{fact.name} 行业分类",
        original_excerpt=excerpt,
        collected_at=datetime.now(UTC),
        evidence_grade="B",
        content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        origin_key=f"baostock:industry:{fact.code}",
    )
    session.add(evidence)
    await session.flush()

    relationship = Relationship(
        source_entity_id=company.id,
        target_entity_id=industry.id,
        relationship_type="belongs_to_industry",
        status="verified",
        confidence=0.7,
        last_verified_at=datetime.now(UTC),
        attributes={
            "classification_source": "project_taxonomy",
            "segment_rationale": rationale,
            "csrc_industry": fact.csrc_industry,
            "review_status": "pending_human_review",
        },
    )
    session.add(relationship)
    await session.flush()

    claim = Claim(
        subject_entity_id=company.id,
        predicate="belongs_to_industry",
        object_entity_id=industry.id,
        claim_type="fact_reported",
        confidence=0.7,
        status="supported",
        needs_human_review=["细分产业归属为项目划分，待人工复核"],
    )
    session.add(claim)
    await session.flush()

    session.add(ClaimRelationship(claim_id=claim.id, relationship_id=relationship.id))
    session.add(
        RelationshipEvidence(
            relationship_id=relationship.id, evidence_id=evidence.id, relation="supporting"
        )
    )
    return True


async def main(apply: bool) -> int:
    data = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    entries = data["companies"]
    codes = [e["code"] for e in entries]

    print(f"universe: {len(entries)} codes declared")
    facts = await fetch_stock_facts(codes)
    print(f"baostock: {len(facts)} codes resolved")

    missing = [c for c in codes if c not in facts]
    if missing:
        print(f"WARNING: {len(missing)} code(s) not found and will be skipped: {missing}")

    if not apply:
        for entry in entries:
            fact = facts.get(entry["code"])
            if fact:
                print(
                    f"  {fact.code:<12} {fact.name:<10} {entry['segment']:<24} "
                    f"csrc={fact.csrc_industry or '-'}"
                )
        print("\ndry run: nothing written (use --apply)")
        return 0

    factory = get_session_factory()
    async with factory() as session:
        await _ensure_source(session)
        industries = await _ensure_industry_entities(session)

        created = 0
        for entry in entries:
            fact = facts.get(entry["code"])
            if fact is None:
                continue
            segment = entry["segment"]
            industry = industries.get(segment)
            if industry is None:
                print(f"  skip {fact.code}: segment {segment} not in taxonomy")
                continue
            company = await _upsert_company(session, fact, segment, entry["rationale"])
            if await _link_industry(session, company, industry, fact, entry["rationale"]):
                created += 1

        await session.commit()
        print(f"\ncompanies upserted: {len([e for e in entries if e['code'] in facts])}")
        print(f"belongs_to_industry edges created: {created}")
        print(f"industry entities: {len(industries)}")

    await dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to the database")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op flag")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(apply=args.apply and not args.dry_run)))
