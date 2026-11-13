"""Collect named counterparties from related-party announcements.

Flow: CNINFO search → filter announcement titles → download PDF → extract text →
pull counterparty names → create CANDIDATE relationships (never verified).

Why candidate: the extractor is pattern-based, so a hit means "this name appears
in a related-party announcement next to a transaction verb". That is good enough
to queue for review, not good enough to assert as fact. Human/QA promotes it.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/collect_related_party.py --dry-run --only 600667
    backend/.venv/Scripts/python.exe scripts/collect_related_party.py --apply --limit 2
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

from app.collectors import cninfo_collector as cninfo  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.core.sortkey import build_sort_key, sort_key_version  # noqa: E402
from app.extractors.pdf import extract_text  # noqa: E402
from app.extractors.related_party import extract_counterparties  # noqa: E402
from app.models.claim import Claim, ClaimRelationship  # noqa: E402
from app.models.entity import Entity  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from app.services.relationship_service import submit_for_review  # noqa: E402
from sqlalchemy import select  # noqa: E402

UNIVERSE = REPO_ROOT / "database" / "seeds" / "ai_compute_universe.yaml"
CACHE = REPO_ROOT / ".cache" / "cninfo"

KEYWORDS = ("关联交易", "日常关联交易")
TITLE_HINTS = ("签署", "合同", "日常", "提供", "采购", "销售", "转让", "共同投资")


def _column(code: str) -> str:
    return "sse" if code.startswith(("6", "9")) else "szse"


def _looks_like_org(name: str) -> bool:
    return name.endswith(("公司", "株式会社", "集团", "厂", "研究院", "研究所"))


async def _counterparty_entity(session, name: str, industry_code: str | None) -> Entity:
    entity = (
        await session.execute(
            select(Entity).where(Entity.canonical_name == name, Entity.entity_type == "private_company")
        )
    ).scalar_one_or_none()
    if entity is not None:
        return entity
    entity = Entity(
        entity_type="private_company",
        canonical_name=name,
        normalized_name=name.strip().lower(),
        name_sort_key=build_sort_key(name),
        name_sort_key_version=sort_key_version(),
        industry_code=industry_code,
        attributes={"data_source": "cninfo_related_party_announcement", "needs_review": True},
    )
    session.add(entity)
    await session.flush()
    return entity


async def main(apply: bool, only: set[str] | None, per_company: int) -> int:
    data = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    codes = [e["code"].split(".")[-1] for e in data["companies"]]
    if only:
        codes = [c for c in codes if c in only]

    print(f"companies: {len(codes)} | mode={'apply' if apply else 'dry-run'} | per_company={per_company}")

    factory = get_session_factory()
    created = queued = 0
    scanned = 0
    failures: list[str] = []

    async with factory() as session:
        for code in codes:
            parent = (
                await session.execute(select(Entity).where(Entity.stock_code == code))
            ).scalar_one_or_none()
            if parent is None:
                failures.append(f"{code}: entity missing")
                continue

            try:
                org_id = await cninfo.find_org_id(code)
                if not org_id:
                    failures.append(f"{code}: orgId not found")
                    continue
                announcements = []
                for kw in KEYWORDS:
                    announcements.extend(
                        await cninfo.search_announcements(code, org_id, kw, column=_column(code), limit=20)
                    )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{code}: search failed {type(exc).__name__}")
                continue

            # De-duplicate and keep only plausible related-party announcements.
            picked, seen_titles = [], set()
            for item in announcements:
                if item.title in seen_titles:
                    continue
                if "关联交易" not in item.title:
                    continue
                if not any(hint in item.title for hint in TITLE_HINTS):
                    continue
                if "摘要" in item.title or "问询" in item.title:
                    continue
                seen_titles.add(item.title)
                picked.append(item)
            picked = picked[:per_company]

            if not picked:
                print(f"  {code}: no candidate announcements")
                continue

            for item in picked:
                scanned += 1
                pdf = CACHE / f"rp_{code}_{item.url.rsplit('/', 1)[-1]}"
                try:
                    if not pdf.exists():
                        await cninfo.download_pdf(item.url, pdf)
                    text = extract_text(pdf)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{code}: pdf {type(exc).__name__}")
                    continue

                hits = [h for h in extract_counterparties(text) if _looks_like_org(h.name)]
                if not hits:
                    continue

                print(f"  {code}: {item.title[:30]} → {len(hits)} counterparties")
                for hit in hits[:3]:
                    print(f"      - {hit.name} ({hit.direction})")
                    if not apply:
                        continue

                    other = await _counterparty_entity(session, hit.name, parent.industry_code)
                    rel_type = hit.direction if hit.direction != "unknown" else "supplies_to"

                    existing = (
                        await session.execute(
                            select(Relationship).where(
                                Relationship.source_entity_id == parent.id,
                                Relationship.target_entity_id == other.id,
                                Relationship.relationship_type == rel_type,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        continue

                    excerpt = f"[{item.title}] {hit.sentence}"
                    evidence = Evidence(
                        source_type="announcement",
                        source_name="巨潮资讯网 · 关联交易公告",
                        source_url=item.url,
                        title=item.title,
                        original_excerpt=excerpt[:900],
                        published_at=(
                            datetime.fromisoformat(item.published_at).replace(tzinfo=UTC)
                            if item.published_at
                            else None
                        ),
                        collected_at=datetime.now(UTC),
                        evidence_grade="A",
                        content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                        origin_key="cninfo:rp:"
                        + hashlib.sha256(f"{item.url}|{hit.name}".encode()).hexdigest()[:48],
                    )
                    session.add(evidence)
                    await session.flush()

                    relationship = Relationship(
                        source_entity_id=parent.id,
                        target_entity_id=other.id,
                        relationship_type=rel_type,
                        status="candidate",
                        confidence=0.5,
                        attributes={
                            "extraction": "related_party_announcement",
                            "direction_hint": hit.direction,
                            "needs_review": True,
                        },
                    )
                    session.add(relationship)
                    await session.flush()

                    claim = Claim(
                        subject_entity_id=parent.id,
                        predicate=rel_type,
                        object_entity_id=other.id,
                        claim_type="fact_reported",
                        confidence=0.6,
                        status="candidate",
                        needs_human_review=["机器抽取的关联方关系，需人工核对公告原文"],
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
                    created += 1

                    # Queue for review; the state guard decides whether it qualifies.
                    try:
                        await submit_for_review(session, relationship.id, actor="system:collector")
                        queued += 1
                    except Exception:  # noqa: BLE001 - threshold not met is a normal outcome
                        pass

            if apply:
                await session.commit()

    await dispose()
    print(f"\nannouncements scanned: {scanned}")
    print(f"relationships created: {created} | queued for review: {queued}")
    if failures:
        print(f"failures: {len(failures)}")
        for line in failures[:20]:
            print("  ", line)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="comma separated stock codes")
    parser.add_argument("--limit", type=int, default=2, help="announcements per company")
    args = parser.parse_args()
    only = {c.strip() for c in args.only.split(",")} if args.only else None
    raise SystemExit(
        asyncio.run(main(apply=args.apply and not args.dry_run, only=only, per_company=args.limit))
    )
