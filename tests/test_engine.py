"""Layered tick engine tests (V0.3)."""

from __future__ import annotations

import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, AssetKind, make_asset_id,
)
from trader_pro.core.engine import DAY, interest_rate_at, bond_price_at, PROFILE_COEFFS  # noqa: E402

U = load_seed_universe()
SEED = 20260614


def _eng(profile="Normal"):
    return MarketEngine(World.new(U, SEED, profile=profile))


def test_fast_forward_matches_step_through() -> None:
    a = _eng(); a.advance(500)
    b = _eng(); b.advance_to(500)
    for aid in U.stocks[:40]:
        sid = make_asset_id(AssetKind.STOCK, aid.symbol)
        assert abs(a.price_at(sid, 500) - b.price_at(sid, 500)) < 1e-9


def test_prices_are_positive_and_bounded_over_two_years() -> None:
    e = _eng()
    for s in U.stocks[:50]:
        sid = make_asset_id(AssetKind.STOCK, s.symbol)
        px = [e.price_at(sid, d * DAY) for d in range(0, 730, 5)]
        assert all(p > 0 for p in px)
        # Mean-reverting: shouldn't explode or vanish over two years.
        assert max(px) / min(px) < 12.0


def test_daily_vol_is_reasonable_and_scales_with_profile() -> None:
    def daily_std(profile):
        e = _eng(profile)
        out = []
        for s in U.stocks[:40]:
            sid = make_asset_id(AssetKind.STOCK, s.symbol)
            px = [e.price_at(sid, d * DAY) for d in range(150)]
            r = [math.log(px[i] / px[i - 1]) for i in range(1, len(px))]
            out.append(st.pstdev(r))
        return st.median(out)

    calm, normal, volatile = daily_std("Calm"), daily_std("Normal"), daily_std("Volatile")
    assert 0.005 < calm < normal < volatile          # monotone in chaos
    assert normal < 0.06                              # not absurd
    assert volatile > normal * 1.3


def test_bond_price_falls_when_rates_rise() -> None:
    b = next(bb for bb in U.bonds if bb.id == "GOVT-30Y")
    coeffs = PROFILE_COEFFS["Normal"]
    # Find two ticks with clearly different rates and compare prices.
    samples = [(interest_rate_at(SEED, t, 0.045, 1.0),
                bond_price_at(SEED, b, t, 0.045, coeffs)) for t in range(0, 365 * DAY, DAY)]
    lo_rate = min(samples); hi_rate = max(samples)
    assert hi_rate[0] > lo_rate[0]
    assert hi_rate[1] < lo_rate[1]                    # higher rate -> lower price


def test_stablecoin_barely_moves_but_meme_swings() -> None:
    e = _eng()
    def daily_std(sym):
        sid = make_asset_id(AssetKind.CRYPTO, sym)
        px = [e.price_at(sid, d * DAY) for d in range(150)]
        return st.pstdev([math.log(px[i] / px[i - 1]) for i in range(1, len(px))])
    assert daily_std("SUSD") < 0.01                   # stablecoin ~ flat
    assert daily_std("FRG") > 0.04                    # meme coin wild


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all engine tests passed")
