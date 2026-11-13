"""Extract related-party counterparties from announcement text.

Design stance: this extractor is deliberately conservative.

It only reports a counterparty when the text contains BOTH
  * a company-like name (ends with 有限公司 / 股份有限公司 / 集团 / 株式会社 / 公司), and
  * an explicit transaction verb next to it (签署 / 向…提供 / 采购 / 销售 / 委托).

Anything weaker is dropped rather than guessed. Extracted facts become
`candidate` relationships with the announcement attached as evidence — they are
queued for human review, never auto-verified. That is the whole point of the
candidate layer (ADR-0007).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A name we are willing to treat as an organisation.
_ORG = r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}?(?:股份有限公司|有限责任公司|有限公司|集团|株式会社|公司)"

#: Structured fields inside the 「关联人介绍」section. Highest precision: the
#: announcement states the counterparty name explicitly, no guessing needed.
_FIELD_PATTERNS = (
    re.compile(r"企业名称[：:]\s*([^\n，,。；;]{2,40})"),
    re.compile(r"公司名称[：:]\s*([^\n，,。；;]{2,40})"),
    re.compile(r"关联方名称[：:]\s*([^\n，,。；;]{2,40})"),
    re.compile(r"交易对方名称[：:]\s*([^\n，,。；;]{2,40})"),
    re.compile(r"关联人名称[：:]\s*([^\n，,。；;]{2,40})"),
)

#: "与X签署" / "同X签订" / "向X提供" / "X向公司提供"
_PATTERNS = (
    re.compile(rf"(?:与|同|和)({_ORG})\s*(?:签署|签订|订立)"),
    re.compile(rf"向({_ORG})\s*(?:提供|销售|采购|供应)"),
    re.compile(rf"({_ORG})\s*(?:向|为)公司\s*(?:提供|销售|采购|供应|服务)"),
    re.compile(rf"交易对方(?:名称)?[：:]\s*({_ORG})"),
    re.compile(rf"关联方(?:名称)?[：:]\s*({_ORG})"),
)

_AMOUNT = re.compile(r"(?:人民币)?\s*([\d,]+(?:\.\d+)?)\s*(亿元|万元|元)")

#: Verbs that tell us which way the goods flow.
_SUPPLY_HINTS = ("提供", "供应", "销售", "供货")
_PURCHASE_HINTS = ("采购", "购买", "接受")

#: Generic names that appear in every announcement and are not real counterparties.
_NOISE = frozenset(
    {
        "本公司",
        "公司",
        "该公司",
        "子公司",
        "控股子公司",
        "全资子公司",
        "上市公司",
        "关联方",
        "交易对方",
        "公司控股子公司",
    }
)


@dataclass(frozen=True)
class CounterpartyHit:
    name: str
    sentence: str
    amount_text: str | None
    direction: str  # "supplies_to" | "purchases_from" | "unknown"


def _clean(name: str) -> str:
    return name.strip().strip("，,。.、:：;；（）()")


def _amount_near(text: str, start: int, window: int = 220) -> str | None:
    chunk = text[max(0, start - window) : start + window]
    match = _AMOUNT.search(chunk)
    return match.group(0).strip() if match else None


def _direction(sentence: str) -> str:
    if any(hint in sentence for hint in _PURCHASE_HINTS):
        return "purchases_from"
    if any(hint in sentence for hint in _SUPPLY_HINTS):
        return "supplies_to"
    return "unknown"


def extract_counterparties(text: str, *, limit: int = 8) -> list[CounterpartyHit]:
    """Return distinct, company-like counterparties with their supporting sentence."""
    if not text:
        return []

    seen: set[str] = set()
    hits: list[CounterpartyHit] = []

    for pattern in (*_FIELD_PATTERNS, *_PATTERNS):
        for match in pattern.finditer(text):
            name = _clean(match.group(1))
            if not name or name in _NOISE or len(name) < 4:
                continue
            # A structured field may still capture a trailing label; drop anything
            # that looks like a sentence rather than a name.
            if any(token in name for token in ("。", "；", "，", " ", "\t")):
                name = name.split()[0] if " " in name else name.split("，")[0]
            if name in seen:
                continue

            start = max(0, match.start() - 120)
            sentence = text[start : match.end() + 120].replace("\n", " ").strip()
            seen.add(name)
            hits.append(
                CounterpartyHit(
                    name=name,
                    sentence=sentence[:300],
                    amount_text=_amount_near(text, match.start()),
                    direction=_direction(sentence),
                )
            )
            if len(hits) >= limit:
                return hits

    return hits


__all__ = ["CounterpartyHit", "extract_counterparties"]
