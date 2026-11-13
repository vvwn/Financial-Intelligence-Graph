"""Baostock collector: real listed-company facts.

What Baostock provides: code, name, IPO date, listing status, CSRC industry
classification. What it does NOT provide: any customer/supplier relationship.
So this collector can populate the entity layer and nothing else.

The library is synchronous and talks a private TCP protocol, so every call is
pushed to a worker thread and wrapped with a timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

import baostock as bs

SOURCE_KEY = "baostock"
CALL_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class StockFact:
    code: str  # e.g. sh.600519
    stock_code: str  # 600519
    exchange: str  # SSE / SZSE
    name: str
    ipo_date: str | None
    out_date: str | None
    status: str
    csrc_industry: str | None


def _normalise(code: str) -> tuple[str, str, str]:
    """`sh.600519` -> (sh.600519, 600519, SSE)."""
    prefix, _, digits = code.partition(".")
    exchange = {"sh": "SSE", "sz": "SZSE", "bj": "BSE"}.get(prefix, "UNKNOWN")
    return code, digits, exchange


def _query_sync(codes: list[str]) -> dict[str, StockFact]:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_code} {login.error_msg}")

    try:
        industry: dict[str, str] = {}
        rs = bs.query_stock_industry()
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()  # [updateDate, code, code_name, industry, classification]
            if len(row) >= 4:
                industry[row[1]] = row[3]

        facts: dict[str, StockFact] = {}
        for code in codes:
            rs = bs.query_stock_basic(code=code)
            if rs.error_code != "0":
                continue
            while rs.next():
                row = rs.get_row_data()
                # [code, code_name, ipoDate, outDate, type, status]
                full_code, stock_code, exchange = _normalise(row[0])
                facts[full_code] = StockFact(
                    code=full_code,
                    stock_code=stock_code,
                    exchange=exchange,
                    name=row[1],
                    ipo_date=row[2] or None,
                    out_date=row[3] or None,
                    status=row[5],
                    csrc_industry=industry.get(full_code),
                )
        return facts
    finally:
        bs.logout()


async def fetch_stock_facts(codes: Iterable[str]) -> dict[str, StockFact]:
    """Fetch basic facts for the given baostock codes (sh.xxxxxx / sz.xxxxxx)."""
    code_list = list(codes)
    if not code_list:
        return {}
    return await asyncio.wait_for(
        asyncio.to_thread(_query_sync, code_list), timeout=CALL_TIMEOUT_SECONDS * 2
    )


__all__ = ["SOURCE_KEY", "StockFact", "fetch_stock_facts"]
