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
from pathlib import Path

#: Different issuers title the same table differently.
SECTION_STARTS = ("企业集团的构成", "在子公司中的权益")
SECTION_START = SECTION_STARTS[0]
SECTION_END_MARKERS = (
    # The notes that always follow the subsidiary table. Any of these means the
    # table is over; without them the slice leaks into 账龄分析 / 前五名客户 tables.
    "在子公司的持股比例不同于表决权比例",
    "持有半数或以下表决权",
    "对于纳入合并范围的重要的结构化主体",
    "确定公司是代理人还是委托人的依据",
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
        # 账龄分析表 / 前五名客户表 里的行，会紧跟在子公司表之后
        "账龄组合",
        "年以上",
        "第一名",
        "第二名",
        "第三名",
        "第四名",
        "第五名",
        "客户一",
        "客户二",
        "客户三",
        "供应商一",
        "供应商二",
        "供应商三",
    }
)
_BAD_PREFIXES = ("及", "的", "其中", "减：", "加：")

#: Legal-form suffixes that reliably terminate a company name in these tables.
#: Anchoring on them beats "first token" because locations and capitals follow.
_NAME_WITH_SUFFIX = re.compile(
    r"^(?P<name>.{2,60}?(?:股份有限公司|有限责任公司|有限公司|株式会社|集团|"
    r"Pte\.?\s?Ltd\.?|Corporation|Corp\.?|Ltd\.?|Inc\.?|S\.r\.l\.?|GmbH|LLC))\s"
)

#: Percentage with or without a trailing '%' — CNINFO tables use both.
_PCT_LOOSE = re.compile(r"(?<![\d,.])(\d{1,3}\.\d{1,2})\s*%?")

#: A row must end with how the stake was obtained; that is what separates table
#: rows from prose and from the ratio tables further down the page.
_ACQUISITION_HINTS = ("设立", "合并", "收购", "新设", "投资设立", "同一控制", "增资", "购买")

#: Tokens that are never a company name, but do show up at the start of a line
#: when the table columns wrap ("设计" is a业务性质, "上海市" is a location).
_NOT_A_NAME = frozenset(
    {
        "设计", "研发", "生产", "销售", "制造", "服务", "投资", "控股", "管理",
        "中国", "美国", "香港", "台湾", "日本", "德国", "新加坡", "韩国", "英国",
        "开曼", "萨摩亚", "泰国", "越南", "印度", "荷兰", "法国", "瑞士", "加拿大",
    }
)

#: A row must also carry a capital figure, otherwise it is prose or a ratio table.
_CAPITAL_SIGNAL = re.compile(r"[\d,]{6,}|美元|万元|港元|欧元|日元|泰铢|人民币")

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
    start = -1
    for heading in SECTION_STARTS:
        found = text.find(heading)
        if found >= 0 and (start < 0 or found < start):
            start = found
    if start < 0:
        return None
    end = len(text)
    for marker in SECTION_END_MARKERS:
        idx = text.find(marker, start + len(SECTION_START))
        if 0 < idx < end:
            end = idx
    return text[start:end]


def _row_name(line: str) -> str | None:
    """Company name at the start of a table row, or None if this line is not a row."""
    match = _NAME_WITH_SUFFIX.match(line)
    if match:
        return match.group("name").strip()

    # Short names without a legal suffix ("中芯上海", "智驰致远").
    token = line.split()[0] if line.split() else ""
    if 2 <= len(token) <= 20 and not any(ch.isdigit() for ch in token):
        return token
    return None


def extract_subsidiaries(text: str) -> SubsidiaryExtraction:
    section = _slice_section(text)
    if section is None:
        return SubsidiaryExtraction(section_found=False)

    result = SubsidiaryExtraction(section_found=True, section_excerpt=section[:1200])
    seen: set[str] = set()

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if len(line) < 6:
            continue
        if not any(hint in line for hint in _ACQUISITION_HINTS):
            continue

        pct_match = None
        for candidate in _PCT_LOOSE.finditer(line):
            value = float(candidate.group(1))
            if 0 < value <= 100:
                pct_match = candidate  # keep the last plausible one
        if pct_match is None:
            continue

        name = _row_name(line)
        if not name:
            continue
        if name in _STOPWORDS or name in _NOT_A_NAME or name.startswith(_BAD_PREFIXES):
            continue
        # A subsidiary name never contains these table artefacts.
        if any(bad in name for bad in ("账龄", "年以上", "第一名", "客户", "供应商", "合计")):
            continue
        has_suffix = bool(
            re.search(r"(有限公司|株式会社|集团|Corporation|Ltd|Inc|GmbH|LLC|S\.r\.l)", name)
        )
        if not has_suffix:
            # Without a legal suffix we only trust short CJK names that sit next to
            # a capital figure — that is what a wrapped table row looks like.
            if not (2 <= len(name) <= 10 and all("\u4e00" <= ch <= "\u9fff" for ch in name)):
                continue
            if not _CAPITAL_SIGNAL.search(line):
                continue
        if name.lower() in _FRAGMENT_HINTS:
            if result.rows:
                prev = result.rows[-1]
                if not prev.needs_review:
                    prev.name = f"{prev.name} {name}"
                result.skipped_fragments += 1
            continue
        if name in seen:
            continue
        seen.add(name)

        row = SubsidiaryRow(
            name=name,
            ownership_pct=float(pct_match.group(1)),
            capital_text=None,
            raw=line[:200],
        )
        if len(name) <= 2:
            row.needs_review = True
            row.review_reason = "名称过短，可能是跨行截断"
        result.rows.append(row)

    return result


__all__ = [
    "SubsidiaryExtraction",
    "SubsidiaryRow",
    "extract_subsidiaries",
    "extract_subsidiaries_auto",
    "extract_subsidiaries_from_pdf",
]


# ---------------------------------------------------------------------------
# Fallback: table-aware extraction with pdfplumber
# ---------------------------------------------------------------------------
#
# The line-based parser above only handles tables where one row stays on one
# line. Many filings wrap long names across 2-3 lines ("智能科技有 / 限公司"),
# which defeats any line regex. pdfplumber reads the ruling lines of the table
# instead, so the cells come back intact.

_TABLE_NAME_HINTS = ("子公司名称", "公司名称", "企业名称")
_TABLE_PCT_HINTS = ("持股比例", "直接", "间接")


_CJK_GAP = re.compile(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])")


def _cell_text(value: object) -> str:
    """Flatten a table cell. pdfplumber injects spaces between CJK glyphs when the
    PDF uses per-character positioning — those must be removed or the name is junk."""
    text = (str(value) if value is not None else "").replace("\n", "").strip()
    return _CJK_GAP.sub("", text)


def _parse_pct(cell: str) -> float | None:
    match = _PCT_LOOSE.search(cell)
    if not match:
        return None
    value = float(match.group(1))
    return value if 0 < value <= 100 else None


def _locate_section_pages(pdf_path: str | Path) -> list[int]:
    """Page indexes containing the heading, found with pypdf (fast).

    pdfplumber's per-page text extraction is ~20x slower, so we use it only on the
    few pages that actually matter.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages: list[int] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
            if any(heading in text for heading in SECTION_STARTS):
                pages.append(index)
        except Exception:  # noqa: BLE001 - a broken page is not fatal
            continue
    return pages


def extract_subsidiaries_from_pdf(
    pdf_path: str | Path, *, max_pages: int = 4, start_pages: list[int] | None = None
) -> SubsidiaryExtraction:
    """Table-aware fallback. Scans a few pages around the section heading."""
    import pdfplumber

    result = SubsidiaryExtraction(section_found=False)
    hit_indexes = start_pages if start_pages is not None else _locate_section_pages(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not hit_indexes:
            return result

        result.section_found = True
        seen: set[str] = set()

        for start in hit_indexes[:2]:
            for page in pdf.pages[start : start + max_pages]:
                for table in page.extract_tables() or []:
                    if not table or len(table) < 2:
                        continue
                    header = " ".join(_cell_text(c) for c in table[0])
                    if not any(h in header for h in _TABLE_NAME_HINTS):
                        continue
                    if not any(h in header for h in _TABLE_PCT_HINTS):
                        continue

                    for raw_row in table[1:]:
                        cells = [_cell_text(c) for c in raw_row]
                        if len(cells) < 2:
                            continue
                        name = cells[0]
                        if not name or len(name) < 2:
                            continue
                        if name in _STOPWORDS or name in _NOT_A_NAME:
                            continue
                        if any(bad in name for bad in ("账龄", "年以上", "第一名", "客户", "供应商", "合计")):
                            continue
                        if name in seen:
                            continue

                        pct = None
                        for cell in reversed(cells[1:]):
                            pct = _parse_pct(cell)
                            if pct is not None:
                                break
                        if pct is None:
                            continue

                        seen.add(name)
                        result.rows.append(
                            SubsidiaryRow(
                                name=name,
                                ownership_pct=pct,
                                capital_text=None,
                                raw=" | ".join(cells)[:200],
                            )
                        )

    return result


def extract_subsidiaries_auto(pdf_path: str | Path) -> SubsidiaryExtraction:
    """Line parser first (fast, no extra dependency); table parser if it finds nothing."""
    from app.extractors.pdf import extract_text

    extraction = extract_subsidiaries(extract_text(pdf_path))
    if extraction.rows:
        return extraction

    fallback = extract_subsidiaries_from_pdf(
        pdf_path, start_pages=_locate_section_pages(pdf_path)
    )
    if fallback.rows:
        return fallback
    return extraction
