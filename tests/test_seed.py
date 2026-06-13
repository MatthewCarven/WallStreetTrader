"""Sanity checks for the generated seed universe (V0.1).

Run with:  python -m pytest   (or)   python tests/test_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import load_seed_universe  # noqa: E402


def test_universe_loads_and_is_populated() -> None:
    u = load_seed_universe()
    assert len(u.stocks) > 400, "expected the full S&P 500 set"
    assert len(u.bonds) >= 20
    assert len(u.crypto) >= 10


def test_stock_parameters_in_plausible_ranges() -> None:
    u = load_seed_universe()
    for s in u.stocks:
        assert s.fair_value > 0
        assert -0.05 <= s.growth_rate <= 0.25
        assert 0.10 <= s.volatility <= 0.70
        assert s.market_cap > 0
        assert s.sector  # non-empty


def test_bond_risk_rises_with_lower_rating() -> None:
    u = load_seed_universe()
    by_rating = {b.rating: b for b in u.bonds if b.issuer_type == "corporate"}
    # Junk should yield more and default more often than investment grade.
    assert by_rating["CCC"].base_yield > by_rating["AAA"].base_yield
    assert by_rating["CCC"].default_prob > by_rating["BBB"].default_prob


def test_crypto_is_high_vol_and_has_a_stablecoin() -> None:
    u = load_seed_universe()
    assert any(c.archetype == "stablecoin" for c in u.crypto)
    risky = [c for c in u.crypto if c.archetype != "stablecoin"]
    assert all(c.volatility >= 0.5 for c in risky), "non-stable coins should be volatile"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all seed tests passed")
