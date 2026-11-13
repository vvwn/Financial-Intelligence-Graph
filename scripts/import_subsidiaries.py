"""Import a listed company's subsidiaries from its annual report.

Pipeline: CNINFO search -> download PDF -> extract text -> parse the
「企业集团的构成」table -> create subsidiary entities + equity edges.

Every edge carries the annual report as grade-A evidence, with the matched row
text as the excerpt, so a reviewer can check it against the PDF.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_subsidiaries.py --code 300308
    backend/.venv/Scripts/python.exe scripts/import_subsidiaries.py --code 300308 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.collectors import cninfo_collector as cninfo  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.extractors.annual_report import extract_subsidiaries  # noqa: E402
from app.extractors.pdf import extract_text  # noqa: E402
from app.models.claim import Claim, ClaimRelationship  # noqa: E402
from app.models.entity import Entity  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

CACHE = REPO_ROOT / ".cache" / "cninfo"


def _column(code: str) -> str:
    return "sse" if code.startswith(("6", "9")) else "szse"


async def _fetch_report(code: str) -> tuple[object, Path]:
    announcement = await cninfo.latest_annual_report(code, column=_column(code))
    if announcement is None:
        raise SystemExit(f"no annual report found for {code}")

    dest = CACHE / f"{code}_annual.pdf"
    if not dest.exists():
        print(f"downloading {announcement.url}")
        await cninfo.download_pdf(announcement.url, dest)
    print(f"report: {announcement.title} ({announcement.published_at}) -> {dest.name}")
    return announcement, dest


async def _upsert_subsidiary(session, parent: Entity, row, announcement) -> Entity | None:
    existing = (
        await session.execute(
            select(Entity).where(
                Entity.canonical_name == row.name, Entity.entity_type == "subsidiary"
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entity = Entity(
        entity_type="subsidiary",
        canonical_name=row.name,
        normalized_name=row.name.strip().lower(),
        name_sort_key=build_sort_key(row.name),
        name_sort_key_version=sort_key_version(),
        industry_code=parent.industry_code,
        attributes={
            "data_source": "cninfo_annual_report",
            "parent_stock_code": parent.stock_code,
            "ownership_pct": row.ownership_pct,
            "capital_text": row.capital_text,
            "report_title": announcement.title,
            "needs_review": row.needs_review,
        },
    )
    session.add(entity)
    await session.flush()
    return entity


async def run(code: str, apply: bool) -> int:
    announcement, pdf_path = await _fetch_report(code)
    text = extract_text(pdf_path)
    print(f"text chars: {len(text)}")

    extraction = extract_subsidiaries(text)
    if not extraction.section_found:
        print("section 「企业集团的构成」 not found — aborting")
        return 2

    print(f"parsed rows: {len(extraction.rows)} "
          f"(clean {len(extraction.clean_rows)}, needs review {len(extraction.rows) - len(extraction.clean_rows)})")
    for row in extraction.rows:
        flag = "  [review]" if row.needs_review else ""
        print(f"  {row.name:<20} {row.ownership_pct:>6.2f}%  cap={row.capital_text}{flag}")

    if not apply:
        print("\ndry run: nothing written (use --apply)")
        return 0

    factory = get_session_factory()
    created = 0
    async with factory() as session:
        parent = (
            await session.execute(select(Entity).where(Entity.stock_code == code))
        ).scalar_one_or_none()
        if parent is None:
            print(f"parent entity {code} not in database — import the universe first")
            return 2

        for row in extraction.rows:
            subsidiary = await _upsert_subsidiary(session, parent, row, announcement)
            if subsidiary is None:
                continue

            rel_type = "controls" if row.ownership_pct >= 50 else "holds_stake_in"
            existing = (
                await session.execute(
                    select(Relationship).where(
                        Relationship.source_entity_id == parent.id,
                        Relationship.target_entity_id == subsidiary.id,
                        Relationship.relationship_type == rel_type,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            excerpt = (
                f"[{announcement.title} · 在其他主体中的权益] {row.raw}"
            )
            evidence = Evidence(
                source_type="annual_report",
                source_name="巨潮资讯网 · 年度报告",
                source_url=announcement.url,
                title=announcement.title,
                original_excerpt=excerpt[:900],
                published_at=(
                    datetime.fromisoformat(announcement.published_at).replace(tzinfo=UTC)
                    if announcement.published_at
                    else None
                ),
                collected_at=datetime.now(UTC),
                evidence_grade="A",
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                origin_key=f"cninfo:{announcement.url.rsplit('/', 1)[-1]}:{row.name}",
            )
            session.add(evidence)
            await session.flush()

            relationship = Relationship(
                source_entity_id=parent.id,
                target_entity_id=subsidiary.id,
                relationship_type=rel_type,
                status="verified",
                confidence=0.95,
                last_verified_at=datetime.now(UTC),
                attributes={
                    "ownership_pct": row.ownership_pct,
                    "evidence_source": "annual_report_subsidiary_table",
                    "needs_review": row.needs_review,
                },
            )
            session.add(relationship)
            await session.flush()

            claim = Claim(
                subject_entity_id=parent.id,
                predicate=rel_type,
                object_entity_id=subsidiary.id,
                claim_type="fact_reported",
                confidence=0.95,
                status="supported",
            )
            session.add(claim)
            await session.flush()

            session.add(ClaimRelationship(claim_id=claim.id, relationship_id=relationship.id))
            session.add(
                RelationshipEvidence(
                    relationship_id=relationship.id, evidence_id=evidence.id, relation="supporting"
                )
            )
            created += 1

        await session.commit()

    await dispose()
    print(f"\nedges created: {created}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="stock code, e.g. 300308")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.code, args.apply)))
