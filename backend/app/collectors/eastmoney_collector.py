"""Eastmoney (东方财富) F10 collector.

Verified on 2026-11-13 against `emweb.securities.eastmoney.com/PC_HSF10/...`:

  OK  CoreConception      ssbk（所属板块）+ hxtc（核心题材，含说明文字）
  OK  ShareholderResearch sjkzr（实际控制人 + 持股比例）
  OK  BusinessAnalysis    zyfw（经营范围）+ zygcfx（主营构成，多期）+ jyps（经营评述全文）
  OK  CompanySurvey       jbzl（基本资料）
  --  datacenter-web 的 RPT_*_CUSTOMER / RPT_*_SUPPLIER  报表不存在

**Eastmoney 同样没有客户/供应商名单。** 经营评述里「客户」出现 30 次，但全是
「下游客户」「云服务厂商」这类泛称，没有一个具名。

它的独特价值在别处：
  * 实际控制人 —— 向上股权穿透，本来以为要靠 gsxt
  * 核心题材 —— 主题归属的书面说明，比我们自己的判断有出处

Code format for this API: SZ300308 / SH600519 / BJ830799.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

BASE = "https://emweb.securities.eastmoney.com/PC_HSF10"
TIMEOUT = 30.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://emweb.securities.eastmoney.com/",
}


@dataclass
class CoreConception:
    boards: list[str] = field(default_factory=list)
    themes: list[dict] = field(default_factory=list)


@dataclass
class ActualController:
    name: str
    hold_ratio: float | None


def em_code(stock_code: str, exchange: str | None = None) -> str:
    """600519 / SSE -> SH600519 ; 300308 / SZSE -> SZ300308."""
    if stock_code[:2] in {"SH", "SZ", "BJ"}:
        return stock_code
    if exchange in {"SSE", "SH"}:
        prefix = "SH"
    elif exchange in {"SZSE", "SZ"}:
        prefix = "SZ"
    elif exchange in {"BSE", "BJ"}:
        prefix = "BJ"
    else:
        prefix = "SH" if stock_code.startswith(("6", "9")) else "SZ"
    return f"{prefix}{stock_code}"


def _get(path: str, code: str) -> dict:
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as c:
        resp = c.get(f"{BASE}/{path}/PageAjax", params={"code": code})
        resp.raise_for_status()
        return resp.json()


def _core_sync(code: str) -> CoreConception:
    data = _get("CoreConception", code)
    boards = [
        row.get("BOARD_NAME", "")
        for row in (data.get("ssbk") or [])
        if row.get("BOARD_NAME")
    ]
    themes = [
        {
            "keyword": row.get("KEYWORD", ""),
            "content": (row.get("MAINPOINT_CONTENT") or "").strip(),
        }
        for row in (data.get("hxtc") or [])
        if row.get("MAINPOINT_CONTENT")
    ]
    return CoreConception(boards=boards, themes=themes)


def _controller_sync(code: str) -> ActualController | None:
    data = _get("ShareholderResearch", code)
    rows = data.get("sjkzr") or []
    if not rows:
        return None
    row = rows[0]
    ratio = row.get("HOLD_RATIO")
    return ActualController(
        name=row.get("HOLDER_NAME", ""),
        hold_ratio=float(ratio) if ratio is not None else None,
    )


async def fetch_core_conception(code: str) -> CoreConception:
    return await asyncio.wait_for(asyncio.to_thread(_core_sync, code), timeout=TIMEOUT * 2)


async def fetch_actual_controller(code: str) -> ActualController | None:
    return await asyncio.wait_for(
        asyncio.to_thread(_controller_sync, code), timeout=TIMEOUT * 2
    )


__all__ = [
    "ActualController",
    "CoreConception",
    "em_code",
    "fetch_actual_controller",
    "fetch_core_conception",
]
