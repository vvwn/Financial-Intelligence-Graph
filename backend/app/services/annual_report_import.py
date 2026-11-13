"""Import a listed company's subsidiaries from its annual report.

Pipeline: CNINFO search -> download PDF -> extract text -> parse the
「企业集团的构成」table -> create subsidiary entities + equity edges.

Every edge carries the annual report as grade-A evidence, with the matched row
text as the excerpt, so a reviewer can check it against the PDF.

Extracted from `scripts/import_subsidiaries.py` so the batch runner and the CLI
share one implementation instead of drifting apart.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import cninfo_collector as cninfo
from app.core.config import REPO_ROOT
from app.core.sortkey import build_sort_key, sort_key_version
from app.extractors.annual_report import (
    extract_subsidiaries,
    extract_subsidiaries_from_pdf,
)
from app.extractors.pdf import extract_text
from app.models.claim import Claim, ClaimRelationship
from app.models.entity import Entity
from app.models.evidence import Evidence
from app.models.relationship import Relationship, RelationshipEvidence

logger = logging.getLogger("fig.import.subsidiaries")

CACHE = REPO_ROOT / ".cache" / "cninfo"


@dataclass
class SubsidiaryImportResult:
    code: str
    ok: bool
    report_title: str | None = None
    parsed: int = 0
    clean: int = 0
    created: int = 0
    error: str | None = None


def _column(code: str) -> str:
    return "sse" if code.startswith(("6", "9")) else "szse"


async def _fetch_report(code: str, cache_dir: Path):
    announcement = await cninfo.latest_annual_report(code, column=_column(code))
    if announcement is None:
        return None, None

    dest = cache_dir / f"{code}_annual.pdf"
    if not dest.exists():
        await cninfo.download_pdf(announcement.url, dest)
    return announcement, dest


async def _upsert_subsidiary(
    session: AsyncSession, parent: Entity, row, announcement
) -> Entity:
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


async def import_for_code(
    session: AsyncSession,
    code: str,
    *,
    cache_dir: Path | None = None,
    require_parent: bool = True,
) -> SubsidiaryImportResult:
    """Import one company's subsidiary table. Never raises for data problems."""
    cache_dir = cache_dir or CACHE
    result = SubsidiaryImportResult(code=code, ok=False)

    parent = (
        await session.execute(select(Entity).where(Entity.stock_code == code))
    ).scalar_one_or_none()
    if parent is None and require_parent:
        result.error = "parent entity not in database"
        return result

    try:
        announcement, pdf_path = await _fetch_report(code, cache_dir)
    except Exception as exc:  # noqa: BLE001 - network failures must not abort a batch
        result.error = f"fetch failed: {type(exc).__name__}: {exc}"
        return result

    if announcement is None:
        result.error = "no annual report found"
        return result

    result.report_title = announcement.title

    # Extracting 200 pages takes ~70s; cache the text next to the PDF so a re-run
    # (or a parser change) does not pay that cost again.
    text_path = pdf_path.with_suffix(".txt")
    try:
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8")
        else:
            text = extract_text(pdf_path)
            text_path.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result.error = f"pdf extract failed: {type(exc).__name__}: {exc}"
        return result

    extraction = extract_subsidiaries(text)
    if not extraction.rows:
        # Tables whose rows wrap across lines defeat the line parser; pdfplumber
        # reads the ruling lines instead. Only replace the result when the
        # fallback actually found rows — otherwise it would overwrite a valid
        # `section_found=True` with False and mask the real state.
        try:
            fallback = extract_subsidiaries_from_pdf(pdf_path)
            if fallback.rows:
                extraction = fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning("table fallback failed for %s: %s", code, exc)
    if not extraction.section_found:
        result.error = "section 「企业集团的构成」 not found"
        return result

    result.parsed = len(extraction.rows)
    result.clean = len(extraction.clean_rows)

    for row in extraction.rows:
        subsidiary = await _upsert_subsidiary(session, parent, row, announcement)

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

        excerpt = f"[{announcement.title} · 在其他主体中的权益] {row.raw}"
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
            # origin_key is varchar(64): hash the URL+name instead of concatenating
            # them, otherwise long Chinese subsidiary names overflow the column.
            origin_key="cninfo:"
            + hashlib.sha256(
                f"{announcement.url}|{row.name}".encode()
            ).hexdigest()[:48],
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
        result.created += 1

    result.ok = True
    return result


__all__ = ["SubsidiaryImportResult", "import_for_code"]
