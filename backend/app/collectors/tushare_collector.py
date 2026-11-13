"""Tushare Pro collector.

Verified on 2026-11-13 with the account behind TUSHARE_TOKEN:

  OK  stock_basic         行业（通信设备）、地区、板块
  OK  index_member_all    申万三级分类，一次调用返回全市场 5916 行
  OK  fina_mainbz         主营构成（按产品），逐公司，响应 <0.3s
  OK  stock_company       主营业务描述、经营范围
  --  ths_index / ths_member   无权限（同花顺概念板块需更高积分）
  --  bak_basic / stk_surv     无权限
  --  report_rc                有权限但限 1 次/分钟

**Tushare 没有客户/供应商数据。** 它提供的是「公司属于哪个行业、卖什么产品」，
不是「它和谁做生意」。所以本模块只用于提升产业归属的证据质量，不建供应链边。

The token is read from the environment (TUSHARE_TOKEN); it is never written to
the repository.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

import tushare as ts

from app.core.config import settings

SOURCE_KEY = "tushare"
CALL_TIMEOUT_SECONDS = 30


def _pro():
    # Read through Settings so the value comes from .env without being exported
    # into the process environment.
    token = (settings.tushare_token or "").strip()
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN is not set; put it in .env (never commit it)"
        )
    ts.set_token(token)
    return ts.pro_api()


@dataclass(frozen=True)
class SwIndustry:
    l1_name: str
    l2_name: str
    l3_name: str


@dataclass(frozen=True)
class RevenueItem:
    item: str
    sales: float
    profit: float | None


def to_ts_code(stock_code: str, exchange: str | None = None) -> str:
    """600519 / SSE -> 600519.SH ; 300308 / SZSE -> 300308.SZ."""
    if "." in stock_code:
        return stock_code
    if exchange in {"SSE", "SH"}:
        suffix = "SH"
    elif exchange in {"SZSE", "SZ"}:
        suffix = "SZ"
    elif exchange in {"BSE", "BJ"}:
        suffix = "BJ"
    else:
        suffix = "SH" if stock_code.startswith(("6", "9")) else "SZ"
    return f"{stock_code}.{suffix}"


def _sw_sync(codes: list[str]) -> dict[str, SwIndustry]:
    pro = _pro()
    df = pro.index_member_all(is_new="Y")
    wanted = set(codes)
    out: dict[str, SwIndustry] = {}
    for row in df.itertuples(index=False):
        if row.ts_code in wanted and row.ts_code not in out:
            out[row.ts_code] = SwIndustry(
                l1_name=row.l1_name or "",
                l2_name=row.l2_name or "",
                l3_name=row.l3_name or "",
            )
    return out


def _mainbz_sync(ts_code: str, period: str) -> list[RevenueItem]:
    pro = _pro()
    df = pro.fina_mainbz(ts_code=ts_code, period=period, type="P")
    items: list[RevenueItem] = []
    for row in df.itertuples(index=False):
        item = (row.bz_item or "").strip()
        # Tushare ships a few non-product rows ("产品" is the table header,
        # "合计特别调整" is an accounting adjustment). Neither is a business line.
        if not item or item in {"产品", "合计"} or "合计" in item or "特别调整" in item:
            continue
        # pandas gives NaN for missing numbers, and NaN is not valid JSON —
        # it would blow up when the value is written into a jsonb column.
        try:
            sales = float(row.bz_sales)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(sales):
            continue
        profit = None
        try:
            candidate = float(row.bz_profit)
            profit = candidate if math.isfinite(candidate) else None
        except (TypeError, ValueError):
            profit = None
        items.append(RevenueItem(item=item, sales=sales, profit=profit))
    items.sort(key=lambda i: i.sales, reverse=True)
    return items


def _profile_sync(ts_code: str) -> dict:
    pro = _pro()
    df = pro.stock_company(ts_code=ts_code, fields="ts_code,main_business,business_scope")
    if df.empty:
        return {}
    row = df.iloc[0]
    return {
        "main_business": (row.get("main_business") or "").strip(),
        "business_scope": (row.get("business_scope") or "").strip(),
    }


async def fetch_sw_industry(ts_codes: list[str]) -> dict[str, SwIndustry]:
    if not ts_codes:
        return {}
    return await asyncio.wait_for(
        asyncio.to_thread(_sw_sync, ts_codes), timeout=CALL_TIMEOUT_SECONDS * 4
    )


async def fetch_revenue_mix(ts_code: str, period: str) -> list[RevenueItem]:
    return await asyncio.wait_for(
        asyncio.to_thread(_mainbz_sync, ts_code, period), timeout=CALL_TIMEOUT_SECONDS
    )


async def fetch_company_profile(ts_code: str) -> dict:
    return await asyncio.wait_for(
        asyncio.to_thread(_profile_sync, ts_code), timeout=CALL_TIMEOUT_SECONDS
    )


__all__ = [
    "SOURCE_KEY",
    "RevenueItem",
    "SwIndustry",
    "fetch_company_profile",
    "fetch_revenue_mix",
    "fetch_sw_industry",
    "to_ts_code",
]
