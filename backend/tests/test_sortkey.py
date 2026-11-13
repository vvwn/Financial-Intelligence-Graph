"""Unit tests for the sort key generator.

These must not depend on database collation or on ICU data: the whole point is
that ordering is decided in the application.
"""

from __future__ import annotations

import pytest
from app.core.sortkey import SORT_KEY_VERSION, build_sort_key


def test_empty_input() -> None:
    assert build_sort_key("") == ""
    assert build_sort_key("   ") == ""


def test_chinese_transliterated() -> None:
    assert build_sort_key("长江电力") == "changjiangdianli"
    assert build_sort_key("宁德时代") == "ningdeshidai"


def test_polyphonic_words_use_phrase_context() -> None:
    """多音字: naive per-character lookup would give zhong/qing and yin/xing."""
    assert build_sort_key("重庆银行").startswith("chongqing")
    assert build_sort_key("重庆") == "chongqing"
    assert build_sort_key("行走") == "xingzou"
    assert build_sort_key("银行") == "yinhang"


def test_ascii_lowercased() -> None:
    assert build_sort_key("ABC") == "abc"
    assert build_sort_key("A股") == "a gu"


def test_digits_zero_padded_for_natural_order() -> None:
    keys = [build_sort_key(s) for s in ("公司5", "公司10", "公司100")]
    assert keys == sorted(keys)


def test_mixed_script_keeps_order_stable() -> None:
    assert build_sort_key("5G通信") == "000005g tongxin"


def test_punctuation_becomes_single_separator() -> None:
    assert build_sort_key("中芯国际-A") == "zhongxinguoji a"
    assert build_sort_key("中芯国际   A") == "zhongxinguoji a"


def test_fullwidth_folded() -> None:
    """NFKC: full-width letters must sort with their ASCII counterparts."""
    assert build_sort_key("ＡＢＣ") == "abc"


def test_deterministic() -> None:
    name = "重庆长安汽车"
    assert build_sort_key(name) == build_sort_key(name)


def test_version_is_exposed() -> None:
    assert SORT_KEY_VERSION == "v1"


@pytest.mark.parametrize(
    "names",
    [
        ["阿里巴巴", "百度", "腾讯"],  # a < b < t
        ["长江电力", "国电南瑞", "许继电气"],  # chang < guo < xu
    ],
)
def test_chinese_sorts_by_pinyin_not_bytes(names: list[str]) -> None:
    by_key = sorted(names, key=build_sort_key)
    by_bytes = sorted(names)
    assert by_key == names, "pinyin order should follow reading order"
    if by_key != by_bytes:
        # Proves the key actually differs from byte ordering; not all cases differ.
        assert build_sort_key(by_key[0]) < build_sort_key(by_key[-1])
