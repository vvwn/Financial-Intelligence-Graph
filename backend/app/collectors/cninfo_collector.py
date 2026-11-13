"""CNINFO (巨潮资讯网) collector.

Verified by hand on 2026-11-13:
  * `topSearch/query`  -> orgId for a stock code
  * `hisAnnouncement/query` -> announcement list with PDF links
  * `static.cninfo.com.cn/finalpage/...PDF` -> direct download

No login or token required. The site's own rate limits are respected via the
caller's schedule; this module never retries in a tight loop.

Note: 国家企业信用信息公示系统 (gsxt.gov.cn) is NOT used here — it answers 521 with
a Riverse JS challenge, and circumventing that is out of scope (see
docs/adr or the datasource investigation report).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE = "http://www.cninfo.com.cn"
STATIC = "http://static.cninfo.com.cn/"
TIMEOUT = 40.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
}


@dataclass(frozen=True)
class Announcement:
    title: str
    url: str
    published_at: str  # ISO date
    adjunct_size_kb: int | None


def _client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)


def _org_id_sync(code: str) -> str | None:
    with _client() as c:
        rows = c.post(f"{BASE}/new/information/topSearch/query",
                      data={"keyWord": code, "maxNum": "10"}).json()
    for row in rows or []:
        if row.get("code") == code:
            return row.get("orgId")
    return rows[0].get("orgId") if rows else None


def _search_sync(code: str, org_id: str, keyword: str, column: str, limit: int) -> list[Announcement]:
    payload = {
        "pageNum": "1",
        "pageSize": str(limit),
        "column": column,
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{org_id}",
        "searchkey": keyword,
        "secDate": "",
        "tdate": "",
        "type": "",
        "trade": "",
        "seDate": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    with _client() as c:
        data = c.post(f"{BASE}/new/hisAnnouncement/query", data=payload).json()

    out: list[Announcement] = []
    for item in data.get("announcements") or []:
        ts = item.get("announcementTime")
        published = ""
        if isinstance(ts, int):
            from datetime import UTC, datetime

            published = datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()
        out.append(
            Announcement(
                title=item.get("announcementTitle", "").replace("<em>", "").replace("</em>", ""),
                url=STATIC + item.get("adjunctUrl", ""),
                published_at=published,
                adjunct_size_kb=item.get("adjunctSize"),
            )
        )
    return out


def _download_sync(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _client() as c:
        resp = c.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


async def find_org_id(code: str) -> str | None:
    return await asyncio.wait_for(asyncio.to_thread(_org_id_sync, code), timeout=TIMEOUT * 2)


async def search_announcements(
    code: str, org_id: str, keyword: str, *, column: str = "szse", limit: int = 30
) -> list[Announcement]:
    return await asyncio.wait_for(
        asyncio.to_thread(_search_sync, code, org_id, keyword, column, limit),
        timeout=TIMEOUT * 2,
    )


async def download_pdf(url: str, dest: Path) -> Path:
    return await asyncio.wait_for(
        asyncio.to_thread(_download_sync, url, dest), timeout=TIMEOUT * 6
    )


async def latest_annual_report(code: str, *, column: str = "szse") -> Announcement | None:
    """The most recent 年度报告 (full text, not the 摘要)."""
    org_id = await find_org_id(code)
    if not org_id:
        return None
    items = await search_announcements(code, org_id, "年度报告", column=column, limit=30)
    # "2026年半年度报告" also contains "年度报告", so the exclusions matter.
    excluded = (
        "摘要", "提示性公告", "英文", "半年度", "季度", "问询", "更正",
        "说明会", "通知", "公告", "H股", "摘要",
    )
    for item in items:
        if any(word in item.title for word in excluded):
            continue
        # The title must actually END with 年度报告 (optionally 全文). A loose
        # "contains 年年度报告" match picks up 「…年度报告网上说明会的通知」.
        if not re.search(r"年年度报告(全文)?$", item.title.strip()):
            continue
        return item
    return None


__all__ = [
    "Announcement",
    "download_pdf",
    "find_org_id",
    "latest_annual_report",
    "search_announcements",
]
