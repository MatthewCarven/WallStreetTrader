"""Unit tests for the shared display formatters (trader_pro/fmt.py)."""
from trader_pro.fmt import money, fmt_qty


def test_money_basic_and_grouping():
    assert money(0) == "$0.00"
    assert money(0.5) == "$0.50"
    assert money(1234.5) == "$1,234.50"
    assert money(1_000_000) == "$1,000,000.00"


def test_money_negative_sign_outside_symbol():
    # -$1,234.50, not $-1,234.50 — the whole point of the helper.
    assert money(-1234.5) == "-$1,234.50"
    assert money(-0.0034) == "-$0.0034"


def test_money_subcent_stays_legible():
    # Penny coins keep ~4 significant figures instead of collapsing to $0.00.
    assert money(0.0000212) == "$0.0000212"
    assert money(0.00005837) == "$0.00005837"
    assert money(0.0034) == "$0.0034"


def test_fmt_qty_whole_numbers_grouped_never_scientific():
    assert fmt_qty(10) == "10"
    assert fmt_qty(1_000_000) == "1,000,000"
    assert fmt_qty(4_709_390.0) == "4,709,390"
    assert "e" not in fmt_qty(1_713_205).lower()


def test_fmt_qty_fractions_scale_decimals_by_magnitude():
    assert fmt_qty(0.5) == "0.5"                 # sub-unit crypto keeps precision
    assert fmt_qty(10.5) == "10.5"               # trailing zero trimmed
    assert fmt_qty(1_713_205.884447) == "1,713,205.88"   # 2dp at scale, not 6


def test_fmt_qty_negative_shorts():
    assert fmt_qty(-1_000_000) == "-1,000,000"
    assert fmt_qty(-0.5) == "-0.5"
