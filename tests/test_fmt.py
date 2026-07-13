"""Unit tests for the shared display formatters (trader_pro/fmt.py)."""
from trader_pro.fmt import money, fmt_qty, abbrev_money, signed_money


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


def test_abbrev_money_for_chart_axes_never_scientific():
    # Chart axis ticks: compact, no 1.2e+06.
    assert abbrev_money(1_200_000) == "$1.2M"
    assert abbrev_money(1_000_000) == "$1M"
    assert abbrev_money(900_000) == "$900k"
    assert abbrev_money(120_000) == "$120k"
    assert abbrev_money(52_540) == "$52.5k"
    assert abbrev_money(152) == "$152"
    assert abbrev_money(-1_200_000) == "-$1.2M"
    for v in (900_000, 1_200_000, 52_540):
        assert "e" not in abbrev_money(v).lower()


def test_abbrev_money_subdollar_falls_back_to_money():
    # Penny-coin price axis stays legible instead of collapsing to $0.
    assert abbrev_money(0.0000073) == money(0.0000073)
    assert abbrev_money(0.99) == "$0.99"


def test_signed_money_keeps_sign_and_symbol():
    assert signed_money(50) == "+$50.00"
    assert signed_money(-50) == "-$50.00"
    assert signed_money(0) == "$0.00"
    assert signed_money(1234.5) == "+$1,234.50"
