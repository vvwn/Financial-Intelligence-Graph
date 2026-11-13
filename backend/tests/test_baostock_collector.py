"""Unit tests for the Baostock adapter's pure helpers.

No network here: the live query is exercised by
`scripts/import_baostock_universe.py --dry-run`, which prints what it resolved.
"""

from __future__ import annotations

import pytest
from app.collectors.baostock_collector import _normalise


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("sh.600519", ("sh.600519", "600519", "SSE")),
        ("sz.300308", ("sz.300308", "300308", "SZSE")),
        ("bj.830799", ("bj.830799", "830799", "BSE")),
    ],
)
def test_normalise_exchange_prefix(code: str, expected: tuple[str, str, str]) -> None:
    assert _normalise(code) == expected


def test_unknown_prefix_is_not_silently_mapped() -> None:
    """An unknown prefix must surface as UNKNOWN, not be guessed."""
    _, _, exchange = _normalise("xx.123456")
    assert exchange == "UNKNOWN"
