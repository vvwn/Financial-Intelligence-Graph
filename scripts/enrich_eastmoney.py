"""Enrich entities with Eastmoney data: actual controller, boards, themes.

Two things this adds that no other connected source provides:

  * 实际控制人 —— upward equity penetration without touching gsxt
  * 核心题材说明 —— a written justification for the thematic (AI-compute) membership,
    so `belongs_to_industry` no longer rests only on our own judgement

It does NOT add supply-chain edges: Eastmoney has no named customer/supplier data.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/enrich_eastmoney.py --dry-run
    backend/.venv/Scripts/python.exe scripts/enrich_eastmoney.py --apply
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

from app.collectors import eastmoney_collector as em  # noqa: E402
from app.core.db import dispose, get_session_factory  # noqa: E402
from app.models.entity import Entity  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.relationship import Relationship, RelationshipEvidence  # noqa: E402
from sqlalchemy import select  # noqa: E402

UNIVERSE = REPO_ROOT / "database" / "seeds" / "ai_compute_universe.yaml"


async def main(apply: bool) -> int:
    data = yaml.safe_load(UNIVERSE.read_text(encoding="utf-8"))
    codes = [e["code"].split(".")[-1] for e in data["companies"]]
    print(f"universe: {len(codes)} companies")

    factory = get_session_factory()
    enriched = 0
    failed: list[str] = []

    async with factory() as session:
        for code in codes:
            entity = (
                await session.execute(select(Entity).where(Entity.stock_code == code))
            ).scalar_one_or_none()
            if entity is None:
                failed.append(f"{code}: entity missing")
                continue

            em_code = em.em_code(code, entity.exchange)
            try:
                core = await em.fetch_core_conception(em_code)
                controller = await em.fetch_actual_controller(em_code)
            except Exception as exc:  # noqa: BLE001 - one bad company must not stop the run
                failed.append(f"{code}: {type(exc).__name__}: {exc}")
                continue

            theme_text = "；".join(
                f"{t['keyword']}：{t['content'][:80]}" for t in core.themes[:3]
            )
            controller_label = controller.name if controller and controller.name else "-"
            print(
                f"  {entity.canonical_name:<12} 板块={','.join(core.boards[:3]):<18} "
                f"实控人={controller_label:<8} 题材={len(core.themes)}"
            )

            if not apply:
                continue

            entity.attributes = {
                **(entity.attributes or {}),
                "em_boards": core.boards,
                "em_themes": [{"keyword": t["keyword"], "content": t["content"][:300]}
                              for t in core.themes[:6]],
                "actual_controller": controller.name if controller else None,
                "actual_controller_ratio": controller.hold_ratio if controller else None,
                "eastmoney_updated_at": datetime.now(UTC).isoformat(),
            }

            relationship = (
                await session.execute(
                    select(Relationship).where(
                        Relationship.source_entity_id == entity.id,
                        Relationship.relationship_type == "belongs_to_industry",
                    )
                )
            ).scalar_one_or_none()

            if relationship is not None and theme_text:
                excerpt = (
                    f"[东方财富 核心题材] {entity.canonical_name}({code})：{theme_text}"
                )
                evidence = Evidence(
                    source_type="research_report",
                    source_name="东方财富 · 核心题材与所属板块",
                    source_url=f"https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/Index?type=web&code={em_code}",
                    title=f"{entity.canonical_name} 核心题材",
                    original_excerpt=excerpt[:900],
                    collected_at=datetime.now(UTC),
                    evidence_grade="C",
                    content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                    origin_key=f"eastmoney:theme:{code}",
                )
                session.add(evidence)
                await session.flush()
                session.add(
                    RelationshipEvidence(
                        relationship_id=relationship.id,
                        evidence_id=evidence.id,
                        relation="supporting",
                    )
                )
                relationship.attributes = {
                    **(relationship.attributes or {}),
                    "taxonomy": "thematic_chain",
                    "thematic_basis": "eastmoney_core_conception",
                }

            enriched += 1

        if apply:
            await session.commit()

    await dispose()
    if failed:
        print(f"\nfailed {len(failed)}:")
        for line in failed:
            print("  ", line)
    print(f"\n{'enriched' if apply else 'would enrich'}: {enriched}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(apply=args.apply and not args.dry_run)))
