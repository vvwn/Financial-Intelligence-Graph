"""Deterministic sort keys for Chinese / mixed-script entity names.

Why this exists: the database runs with `locale=C` (ADR-0009). Sorting by the raw
name would order Chinese by byte value, not by reading order. We therefore compute
a sort key in the application and store it, so no deployment depends on ICU data
being present in the PostgreSQL image.

Rules:
  - the original name is never modified
  - CJK runs are transliterated to toneless pinyin (phrase-aware, so 重庆 -> chong qing)
  - ASCII is lower-cased; digit runs are zero-padded so 5 < 10 < 100 sorts naturally
  - punctuation and whitespace collapse to a single separator

Bump SORT_KEY_VERSION whenever the algorithm changes; every entity stores the
version it was computed with, and changes are recorded in entity_sort_key_history.
"""

from __future__ import annotations

import re
import unicodedata

from pypinyin import Style, lazy_pinyin

#: Bump on any behavioural change. Stored per entity; history rows record the change.
SORT_KEY_VERSION = "v1"

DIGIT_WIDTH = 6

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_ALNUM = re.compile(r"[0-9A-Za-z]+")
_DIGITS = re.compile(r"\d+")


def _pad_digits(token: str) -> str:
    return _DIGITS.sub(lambda m: m.group(0).zfill(DIGIT_WIDTH), token)


def _cjk_run(text: str) -> str:
    """Transliterate a CJK run. lazy_pinyin is phrase-aware for common words."""
    return "".join(lazy_pinyin(text, style=Style.NORMAL, errors="default"))


def build_sort_key(name: str) -> str:
    """Return a collation-independent sort key. Empty input yields an empty key."""
    if not name:
        return ""

    # NFKC folds full-width ASCII (Ａ -> A) and compatibility forms.
    text = unicodedata.normalize("NFKC", name).strip()
    if not text:
        return ""

    parts: list[str] = []
    last_kind: str | None = None

    def _push(kind: str, value: str) -> None:
        nonlocal last_kind
        # Separate script switches with a space so "5G通信" -> "000005g tongxin"
        # instead of gluing latin and pinyin into one ambiguous token.
        if last_kind is not None and last_kind != kind and parts and parts[-1] != " ":
            parts.append(" ")
        parts.append(value)
        last_kind = kind

    i = 0
    while i < len(text):
        m = _CJK.match(text, i)
        if m:
            _push("cjk", _cjk_run(m.group(0)))
            i = m.end()
            continue

        m = _ALNUM.match(text, i)
        if m:
            _push("alnum", _pad_digits(m.group(0).lower()))
            i = m.end()
            continue

        # punctuation / whitespace -> separator
        if parts and parts[-1] != " ":
            parts.append(" ")
        last_kind = None
        i += 1

    return "".join(parts).strip()


def sort_key_version() -> str:
    return SORT_KEY_VERSION


__all__ = ["DIGIT_WIDTH", "SORT_KEY_VERSION", "build_sort_key", "sort_key_version"]
