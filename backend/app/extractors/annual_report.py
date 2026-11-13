"""Extract structured facts from annual-report text.

Current scope: the subsidiary table under
「附注 · 在其他主体中的权益 · 企业集团的构成」, which lists every consolidated
subsidiary with its registered capital and ownership percentage.

Why this matters: it is the only publicly available, A-grade source of the
equity layer. 国家企业信用信息公示系统 would give similar data, but it sits behind
a Riverse JS challenge, and its data is not needed for listed companies because
the annual report already discloses the full subsidiary list.

Known limitation: PDF text extraction scrambles table columns, so multi-line
names ("TeraHop Pte") may be split. The parser merges short latin fragments back
into the previous name and flags anything suspicious for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_START = "企业集团的构成"
SECTION_END_MARKERS = (
    "2、在子公司的所有者权益份额",
    "3、在合营企业",
    "在合营企业或联营企业中的权益",
    "在合营企业和联营企业中的权益",
)

#: Rows that appear inside the section but are not subsidiaries: totals, ratio
#: tables, and business-description fragments left behind by PDF layout.
_STOPWORDS = frozenset(
    {
        "合计",
        "小计",
        "投资控股",
        "应收单位",
        "利润",
        "公司普通股股东的净利润",
        "少数股东",
        "及服务",
        "及生产",
        "及研发",
        "及贸易",
    }
)
_BAD_PREFIXES = ("及", "的", "其中", "减：", "加：")

_ROW = re.compile(
    r"(?P<name>[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{1,24})\s+"
    r"(?P<capital>[\d,]+(?:\.\d+)?)"
    r"[^\n]{0,80}?"
    r"(?P<pct>\d{1,3}\.\d{2})%"
)

#: Fragments that are almost certainly a continuation of the previous name.
_FRAGMENT_HINTS = {"pte", "ltd", "inc", "co", "us", "hk", "thailand", "holdings", "photonics"}


@dataclass
class SubsidiaryRow:
    name: str
    ownership_pct: float
    capital_text: str | None = None
    raw: str = ""
    needs_review: bool = False
    review_reason: str | None = None


@dataclass
class SubsidiaryExtraction:
    rows: list[SubsidiaryRow] = field(default_factory=list)
    section_found: bool = False
    section_excerpt: str = ""
    skipped_fragments: int = 0

    @property
    def clean_rows(self) -> list[SubsidiaryRow]:
        return [r for r in self.rows if not r.needs_review]


def _slice_section(text: str) -> str | None:
    start = text.find(SECTION_START)
    if start < 0:
        return None
    end = len(text)
    for marker in SECTION_END_MARKERS:
        idx = text.find(marker, start + len(SECTION_START))
        if 0 < idx < end:
            end = idx
    return text[start:end]


def extract_subsidiaries(text: str) -> SubsidiaryExtraction:
    section = _slice_section(text)
    if section is None:
        return SubsidiaryExtraction(section_found=False)

    result = SubsidiaryExtraction(section_found=True, section_excerpt=section[:1200])
    seen: set[str] = set()

    for match in _ROW.finditer(section):
        name = match.group("name").strip()
        pct = float(match.group("pct"))
        raw = match.group(0)

        if pct <= 0 or pct > 100:
            continue

        lowered = name.lower()
        if name in _STOPWORDS or name.startswith(_BAD_PREFIXES):
            continue
        capital_value = float(match.group("capital").replace(",", "") or 0)
        if capital_value < 10_000:
            # Real registered capital is at least 万元级; smaller numbers come from
            # ratio tables that happen to sit in the same slice.
            continue
        if lowered in _FRAGMENT_HINTS:
            if result.rows:
                # Continuation of the previous name, e.g. "TeraHop" + "Pte".
                prev = result.rows[-1]
                if not prev.needs_review:
                    prev.name = f"{prev.name} {name}"
                    prev.raw = f"{prev.raw} | {raw}"
                result.skipped_fragments += 1
                continue
            # A fragment with nothing to attach to: keep it, but flag it so it is
            # never treated as a clean subsidiary name.
            fragment = SubsidiaryRow(
                name=name,
                ownership_pct=pct,
                capital_text=match.group("capital"),
                raw=raw[:200],
                needs_review=True,
                review_reason="疑似跨行截断的英文片段（无前序名称可合并）",
            )
            result.rows.append(fragment)
            continue

        if name in seen:
            continue
        seen.add(name)

        row = SubsidiaryRow(
            name=name,
            ownership_pct=pct,
            capital_text=match.group("capital"),
            raw=raw[:200],
        )
        if len(name) <= 2:
            row.needs_review = True
            row.review_reason = "名称过短，可能是跨行截断"
        elif lowered.isascii() and len(name) <= 3:
            row.needs_review = True
            row.review_reason = "疑似跨行截断的英文片段"
        result.rows.append(row)

    return result


__all__ = [
    "SubsidiaryExtraction",
    "SubsidiaryRow",
    "extract_subsidiaries",
]
