"""Unit tests for the related-party extractor.

The sample is a trimmed copy of the real 太极实业 announcement text
(巨潮 finalpage/2025-06-19/1223910508.PDF), keeping the layout quirks.
"""

from __future__ import annotations

from app.extractors.related_party import extract_counterparties

SAMPLE = """
一、关联交易概述
2009年，公司实施重大资产重组，与韩国（株）海力士半导体（现爱思开海力士株式会社）
签署《合资协议》《合资经营合同》，合资设立海太半导体，公司持有海太半导体55%股权。
由海太半导体向SK海力士提供半导体后工序服务。
二、关联人介绍
1、企业名称：爱思开海力士株式会社
2、总部地址：韩国京畿道利川市夫钵邑京忠大路2091
3、代表董事：郭鲁正
4、主营业务：半导体元件制造和销售
"""


def test_extracts_name_from_structured_field() -> None:
    """「企业名称：」is the most reliable anchor in a 关联人介绍 section."""
    hits = extract_counterparties(SAMPLE)

    names = [h.name for h in hits]
    assert "爱思开海力士株式会社" in names


def test_direction_hint_present() -> None:
    hits = extract_counterparties(SAMPLE)
    hit = next(h for h in hits if h.name == "爱思开海力士株式会社")

    assert hit.direction in {"supplies_to", "purchases_from", "unknown"}


def test_sentence_is_attached() -> None:
    hits = extract_counterparties(SAMPLE)
    hit = next(h for h in hits if h.name == "爱思开海力士株式会社")

    assert hit.sentence
    assert len(hit.sentence) <= 300


def test_generic_names_are_dropped() -> None:
    hits = extract_counterparties("交易对方：本公司；公司名称：子公司")

    assert all(h.name not in {"本公司", "子公司", "公司"} for h in hits)


def test_empty_text_returns_nothing() -> None:
    assert extract_counterparties("") == []


def test_no_fabrication_without_anchor() -> None:
    """Free text with no explicit name must not produce a counterparty."""
    hits = extract_counterparties("公司向下游客户提供光模块产品，订单饱满，产能利用率高。")

    assert hits == []
