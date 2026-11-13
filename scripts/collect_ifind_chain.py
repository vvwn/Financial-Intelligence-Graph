"""Build the industry-chain map from iFinD, quota-aware.

Two modes:

  --probe     fetch the chain tree (1 call, cached forever) and show which iFinD
              nodes match our 15 AI-compute segments. No atlas calls.
  --build     also fetch atlas for the matched nodes (1 call per node).

Every call is logged with its parameters so the local ledger can be reconciled
against the iFinD console. Responses are cached on disk — a re-run of the same
question costs nothing, which matters because the server does not cache.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/collect_ifind_chain.py --probe
    backend/.venv/Scripts/python.exe scripts/collect_ifind_chain.py --build --budget 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.collectors.ifind_collector import (  # noqa: E402
    IfindClient,
    QuotaBudgetExceeded,
    chain_atlas,
    chain_tree,
    find_node,
)

SEED = REPO_ROOT / "database" / "seeds" / "industries.yaml"

#: Our segment name -> candidate keywords in the iFinD chain tree.
#: A node may match several keywords; the first exact hit wins.
KEYWORDS = {
    "AI-COMPUTE-GPU": ["GPU", "图形处理器", "智能芯片"],
    "AI-COMPUTE-ASIC": ["ASIC", "集成电路设计"],
    "AI-COMPUTE-FOUNDRY": ["晶圆制造", "晶圆代工", "晶圆"],
    "AI-COMPUTE-PACKAGING": ["封装测试", "集成电路封装", "封装"],
    "AI-COMPUTE-EQUIPMENT": ["半导体设备"],
    "AI-COMPUTE-MATERIAL": ["半导体材料"],
    "AI-COMPUTE-SERVER": ["服务器"],
    "AI-COMPUTE-OPTICAL": ["光模块"],
    "AI-COMPUTE-OPTICAL-DEVICE": ["光通信器件", "光器件"],
    "AI-COMPUTE-SWITCH": ["交换机", "网络设备"],
    "AI-COMPUTE-PCB": ["印制电路板", "PCB"],
    "AI-COMPUTE-COOLING": ["液冷", "制冷空调设备", "温控设备"],
    "AI-COMPUTE-POWER": ["电源设备", "电源"],
    "AI-COMPUTE-CONNECTOR": ["电连接器", "连接器"],
    "AI-COMPUTE-IDC": ["IDC服务", "数据中心"],
}


def main(probe_only: bool, budget: int) -> int:
    segments = yaml.safe_load(SEED.read_text(encoding="utf-8"))["industries"]
    codes = [s["code"] for s in segments if s["code"].startswith("AI-COMPUTE-")]

    client = IfindClient("enterprise", budget=budget)
    try:
        print(f"budget: {budget} calls | 已用 0\n")
        tree = chain_tree(client)
        print(f"产业链树已获取（缓存后不再消耗）：{len(tree)} 个一级节点")

        mapping: dict[str, tuple[str, str, int]] = {}
        fuzzy: list[str] = []
        print(f"\n{'我们的分类':<28} {'iFinD 节点':<22} {'code':<8} {'level':<6} 精确")
        print("-" * 82)
        for code in codes:
            hit = None
            keyword_hit = ""
            for keyword in KEYWORDS.get(code, []):
                found = find_node(tree, keyword)
                if found:
                    hit = found[0]
                    keyword_hit = keyword
                    break
            if hit:
                exact = hit[1] == keyword_hit
                mapping[code] = hit
                if not exact:
                    fuzzy.append(code)
                print(f"{code:<28} {hit[1]:<22} {hit[0]:<8} {hit[2]:<6} {'是' if exact else '否 ←需人工确认'}")
            else:
                print(f"{code:<28} {'（未匹配）':<22}")

        print(f"\n匹配 {len(mapping)}/{len(codes)}，其中精确 {len(mapping) - len(fuzzy)}，模糊 {len(fuzzy)}")
        if fuzzy:
            print(f"模糊匹配（默认不拉 atlas，避免用错节点）：{', '.join(fuzzy)}")

        if not probe_only and mapping:
            print("\n=== 拉取 atlas（每个节点 1 次）===")
            for code, (node_code, node_name, _) in mapping.items():
                if code in fuzzy:
                    print(f"  {code}: 跳过（模糊匹配 {node_name}）")
                    continue
                try:
                    atlas = chain_atlas(client, node_code)
                except QuotaBudgetExceeded as exc:
                    print(f"  {code}: 预算用尽 — {exc}")
                    break
                if not atlas:
                    print(f"  {code}: {node_name} — atlas 为空")
                    continue
                up = [n["node_name"] for g in atlas.get("up_stream", []) for n in g.get("list", [])]
                down = [
                    n["node_name"] for g in atlas.get("down_stream", []) for n in g.get("list", [])
                ]
                print(f"  {code}: {node_name}")
                print(f"      上游: {', '.join(up[:4]) or '-'}")
                print(f"      下游: {', '.join(down[:4]) or '-'}")

        summary = client.ledger.summary()
        print(f"\n=== 本次消耗 {summary['calls']} 次（成功 {summary['ok']} / 失败 {summary['failed']}）===")
        print(json.dumps(summary["detail"], ensure_ascii=False, indent=2)[:1200])
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="tree only, no atlas calls")
    parser.add_argument("--build", action="store_true", help="also fetch atlas per node")
    parser.add_argument("--budget", type=int, default=10, help="hard cap on tool calls")
    args = parser.parse_args()
    raise SystemExit(main(probe_only=not args.build, budget=args.budget))
