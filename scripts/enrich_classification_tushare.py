"""Enrich industry classification with Tushare-sourced evidence.

Before: `belongs_to_industry` edges were justified by the project's own taxonomy
judgement (attributes.classification_source = "project_taxonomy").

After: each edge additionally carries
  * 申万三级行业分类（第三方指数公司的标准分类）
  * 公司自己披露的主营构成（按产品的营收拆分）
so the edge rests on citable data rather than on our judgement alone.

Tushare has no customer/supplier data, so this script does NOT create supply-chain
edges. It only strengthens the classification layer.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/enrich_classification_tushare.py --dry-run
    backend/.venv/Scripts/python.exe scripts/enrich_classification_tushare.py --apply
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

from app.collectors import tushare_collector as tushare  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.models.entity import Entity  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

UNIVERSE = REPO_ROOT / "database" / "seeds" / "ai_compute_universe.yaml"
REPORT_PERIOD = "20251231"


def _fmt_money(value: float) -> str:
    return f"{value / 1e8:.2f} 亿元"


async def main(apply: bool) -> int:
    data = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    codes = [e["code"].split(".")[-1] for e in data["companies"]]
    ts_codes = {c: tushare.to_ts_code(c) for c in codes}

    print(f"universe: {len(codes)} companies")
    sw = await tushare.fetch_sw_industry(list(ts_codes.values()))
    print(f"申万分类命中: {len(sw)}/{len(codes)}")

    factory = get_session_factory()
    enriched = 0
    skipped: list[str] = []

    async with factory() as session:
        for code, ts_code in ts_codes.items():
            entity = (
                await session.execute(select(Entity).where(Entity.stock_code == code))
            ).scalar_one_or_none()
            if entity is None:
                skipped.append(f"{code}: entity missing")
                continue

            industry = sw.get(ts_code)
            mix = await tushare.fetch_revenue_mix(ts_code, REPORT_PERIOD)
            profile = await tushare.fetch_company_profile(ts_code)

            top = mix[0] if mix else None
            total = sum(i.sales for i in mix) or 0.0
            top_share = (top.sales / total * 100) if top and total else None

            label = f"{entity.canonical_name}({code})"
            print(
                f"  {label:<18} 申万={industry.l3_name if industry else '-':<16} "
                f"主营首位={top.item if top else '-':<14} "
                f"{f'{top_share:.1f}%' if top_share else '-':>6}"
            )

            if not apply:
                continue

            entity.attributes = {
                **(entity.attributes or {}),
                "sw_l1": industry.l1_name if industry else None,
                "sw_l2": industry.l2_name if industry else None,
                "sw_l3": industry.l3_name if industry else None,
                "revenue_mix": [
                    {
                        "item": i.item,
                        "sales": i.sales,
                        "share_pct": round(i.sales / total * 100, 2) if total else None,
                    }
                    for i in mix[:5]
                ],
                "main_business": profile.get("main_business") or None,
                "classification_updated_at": datetime.now(UTC).isoformat(),
            }

            relationship = (
                await session.execute(
                    select(Relationship).where(
                        Relationship.source_entity_id == entity.id,
                        Relationship.relationship_type == "belongs_to_industry",
                    )
                )
            ).scalar_one_or_none()
            if relationship is None:
                skipped.append(f"{code}: no belongs_to_industry edge")
                continue

            parts = []
            if industry:
                parts.append(
                    f"申万三级：{industry.l3_name}（{industry.l1_name} / {industry.l2_name}）"
                )
            if top:
                parts.append(
                    f"主营构成（{REPORT_PERIOD}）：{top.item} {_fmt_money(top.sales)}"
                    + (f"，占 {top_share:.2f}%" if top_share else "")
                )
            if profile.get("main_business"):
                parts.append(f"公司主营业务：{profile['main_business'][:120]}")
            excerpt = "；".join(parts)

            if not excerpt:
                skipped.append(f"{code}: tushare returned nothing")
                continue

            evidence = Evidence(
                source_type="research_report",
                source_name="Tushare Pro · 申万行业分类 + 主营构成",
                source_url="https://tushare.pro",
                title=f"{entity.canonical_name} 行业分类与主营构成",
                original_excerpt=excerpt[:900],
                collected_at=datetime.now(UTC),
                evidence_grade="B",
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                origin_key=f"tushare:{ts_code}:{REPORT_PERIOD}",
            )
            session.add(evidence)
            await session.flush()

            already = (
                await session.execute(
                    select(RelationshipEvidence).where(
                        RelationshipEvidence.relationship_id == relationship.id,
                        RelationshipEvidence.evidence_id == evidence.id,
                    )
                )
            ).scalar_one_or_none()
            if already is None:
                session.add(
                    RelationshipEvidence(
                        relationship_id=relationship.id,
                        evidence_id=evidence.id,
                        relation="supporting",
                    )
                )

            relationship.attributes = {
                **(relationship.attributes or {}),
                "classification_source": "sw_industry+mainbz",
                "sw_l3": industry.l3_name if industry else None,
                "top_product": top.item if top else None,
                "top_product_share_pct": round(top_share, 2) if top_share else None,
            }
            enriched += 1

        if apply:
            await session.commit()

    await dispose()

    if skipped:
        print(f"\nskipped {len(skipped)}:")
        for line in skipped:
            print("  ", line)

    print(f"\n{'enriched' if apply else 'would enrich'}: {enriched}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(apply=args.apply and not args.dry_run)))
