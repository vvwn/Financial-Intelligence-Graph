"""Load the cached iFinD chain data into PostgreSQL.

Reads only from the local response cache — this script never calls the API, so it
cannot consume quota. Run `collect_ifind_chain.py` first to fill the cache.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_ifind_chain.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.models.chain import IndustryChainEdge, IndustryChainNode  # noqa: E402
from sqlalchemy import select  # noqa: E402

CACHE = REPO_ROOT / ".cache" / "ifind" / "responses"
SEED = REPO_ROOT / "database" / "seeds" / "industries.yaml"

#: iFinD atlas group -> our relation name
GROUP_TO_RELATION = {
    "up_stream": "upstream",
    "down_stream": "downstream",
    "replace_stream": "replace",
    "comp_stream": "complement",
    "contains_stream": "contains",
}

#: Our segment -> iFinD node code, resolved by hand after the probe run.
#: Only exact matches are listed; fuzzy ones are intentionally absent.
SEGMENT_TO_NODE = {
    "AI-COMPUTE-GPU": "2094",
    "AI-COMPUTE-ASIC": "2048",
    "AI-COMPUTE-MATERIAL": "2549",
    "AI-COMPUTE-EQUIPMENT": "2707",
    "AI-COMPUTE-SERVER": "20",
    "AI-COMPUTE-OPTICAL": "23992",
    "AI-COMPUTE-OPTICAL-DEVICE": "23979",
    "AI-COMPUTE-SWITCH": "30135",
    "AI-COMPUTE-PCB": "2899",
    "AI-COMPUTE-COOLING": "10009",
    "AI-COMPUTE-POWER": "1829",
    "AI-COMPUTE-CONNECTOR": "2294",
    "AI-COMPUTE-IDC": "586",
}


def _load_cache(pattern: str) -> list[dict]:
    out = []
    for path in sorted(CACHE.glob(pattern)):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _tree_nodes() -> list[dict]:
    """Flatten the chain tree into (code, name, level, parent)."""
    trees = _load_cache("filter_get_industry_chain_tree_structure_*.json")
    if not trees:
        return []
    raw = json.loads(trees[-1]["data"]["data"]["raw"])
    flat: list[dict] = []

    def walk(nodes: list[dict], parent: str | None) -> None:
        for node in nodes:
            flat.append(
                {
                    "code": node["node_code"],
                    "name": node.get("node_name", ""),
                    "level": node.get("level"),
                    "parent_code": parent,
                }
            )
            walk(node.get("sub_node") or [], node["node_code"])

    walk(raw["data"]["list"], None)

    # A node can hang under several parents in the iFinD tree; the table keys on
    # code, so keep the first occurrence (shallowest, because DFS is pre-order).
    seen: dict[str, dict] = {}
    for node in flat:
        seen.setdefault(node["code"], node)
    return list(seen.values())


def _atlas_edges() -> list[dict]:
    edges: list[dict] = []
    for payload in _load_cache("filter_get_industry_chain_atlas_*.json"):
        if payload.get("data", {}).get("status_code") != 0:
            continue
        atlas = json.loads(payload["data"]["data"]["raw"])["data"]
        src = atlas.get("node_code")
        if not src:
            continue
        for group, relation in GROUP_TO_RELATION.items():
            for bucket in atlas.get(group) or []:
                for node in bucket.get("list") or []:
                    edges.append(
                        {"src": src, "dst": node["node_code"], "relation": relation}
                    )
    return edges


async def main(apply: bool) -> int:
    nodes = _tree_nodes()
    edges = _atlas_edges()
    print(f"缓存解析：节点 {len(nodes)}，产业链边 {len(edges)}")

    # The atlas sometimes references nodes that are not in the tree slice we
    # fetched. Dropping those is correct — inventing a node would be worse.
    known = {n["code"] for n in nodes}
    orphan = [e for e in edges if e["src"] not in known or e["dst"] not in known]
    edges = [e for e in edges if e["src"] in known and e["dst"] in known]
    if orphan:
        print(f"丢弃 {len(orphan)} 条边（端点不在树中，例如 {orphan[0]}）")

    segments = {s["code"] for s in yaml.safe_load(SEED.read_text(encoding="utf-8"))["industries"]}
    mapped = {code: seg for seg, code in SEGMENT_TO_NODE.items() if seg in segments}
    print(f"产业映射：{len(mapped)} 个 iFinD 节点对应到我们的细分产业")

    if not apply:
        print("\n样本节点：", nodes[:3])
        print("样本边：", edges[:3])
        print("\ndry run：未写库")
        return 0

    factory = get_session_factory()
    async with factory() as session:
        # Nodes: insert or update.
        existing = {
            row.code: row
            for row in (await session.execute(select(IndustryChainNode))).scalars().all()
        }
        created = updated = 0
        for node in nodes:
            row = existing.get(node["code"])
            if row is None:
                session.add(
                    IndustryChainNode(
                        code=node["code"],
                        name=node["name"],
                        level=node["level"],
                        parent_code=node["parent_code"],
                        mapped_segment=mapped.get(node["code"]),
                    )
                )
                created += 1
            else:
                row.name = node["name"]
                row.level = node["level"]
                row.parent_code = node["parent_code"]
                if node["code"] in mapped:
                    row.mapped_segment = mapped[node["code"]]
                updated += 1
        await session.flush()

        # Edges: the tree must exist first (FK), which it now does.
        have = {
            (e.src_code, e.dst_code, e.relation)
            for e in (await session.execute(select(IndustryChainEdge))).scalars().all()
        }
        added = 0
        batch_seen: set[tuple[str, str, str]] = set()
        for edge in edges:
            key = (edge["src"], edge["dst"], edge["relation"])
            if key in have or key in batch_seen:
                continue
            batch_seen.add(key)
            session.add(
                IndustryChainEdge(src_code=edge["src"], dst_code=edge["dst"], relation=edge["relation"])
            )
            added += 1

        await session.commit()
        print(f"\n节点：新增 {created}，更新 {updated}")
        print(f"产业链边：新增 {added}（缓存中共 {len(edges)} 条）")

    await dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(apply=args.apply)))
