"""Unit tests for the annual-report extractor.

No network and no database: the sample below is a trimmed copy of the real
subsidiary table from 中际旭创 2025 年年度报告 (page 199), kept verbatim including
the column-scrambling that PDF extraction produces.
"""

from __future__ import annotations

from app.extractors.annual_report import extract_subsidiaries

SAMPLE = """
十、在其他主体中的权益
1、在子公司中的权益
（1） 企业集团的构成
单位：元
子公司名称 注册资本 主要经营地 注册地 业务性质
持股比例
取得方式
直接 间接
苏州旭创 2,834,600, 000.00 苏州 苏州 设计、研发 及生产 100.00%  合并
储翰科技 103,000,00 0.00 成都 成都 设计、研发 及生产 99.74%  合并
深度智冷 100,000,00 0.00 广东 广东 设计、研发 及生产 51.00%  设立
TeraHop
Pte
228,000,00
0.00
美元
 新加坡 新加坡 投资、贸易 及服务  67.71% 设立
合计 -- 100.00% 3,000,000,000.00
2、在子公司的所有者权益份额发生变化仍具有控制权的交易
无
3、在合营企业或联营企业中的权益
（1） 重要的合营企业或联营企业
"""


def test_extracts_named_subsidiaries_with_percentages() -> None:
    result = extract_subsidiaries(SAMPLE)

    assert result.section_found is True
    names = {r.name: r.ownership_pct for r in result.rows}
    assert names["苏州旭创"] == 100.00
    assert names["储翰科技"] == 99.74
    assert names["深度智冷"] == 51.00


def test_split_latin_names_are_never_treated_as_clean() -> None:
    """'TeraHop' / 'Pte' arrive on separate lines.

    The parser either merges the fragment into the previous name or flags it for
    review — it must never present a bare fragment as a verified subsidiary.
    """
    result = extract_subsidiaries(SAMPLE)

    fragments = [r for r in result.rows if r.name.lower() in {"pte", "ltd", "inc"}]
    assert all(r.needs_review for r in fragments), "a bare fragment must be flagged"
    assert all(not r.needs_review for r in result.rows if r.name in {"苏州旭创", "储翰科技"})


def test_drops_total_row() -> None:
    result = extract_subsidiaries(SAMPLE)

    assert not any(r.name in {"合计", "小计"} for r in result.rows)


def test_section_boundary_excludes_equity_method_note() -> None:
    """The slice must stop before 合营/联营, otherwise ratio tables leak in."""
    result = extract_subsidiaries(SAMPLE)

    assert "合营企业或联营企业" not in result.section_excerpt


def test_missing_section_is_reported_not_raised() -> None:
    result = extract_subsidiaries("完全无关的文本")

    assert result.section_found is False
    assert result.rows == []
