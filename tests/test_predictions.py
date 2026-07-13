"""Prediction system tests (V1.5)."""
from __future__ import annotations
import statistics as st, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, make_asset_id, AssetKind, make_prediction, quote_cost,
)
from trader_pro.core.engine import DAY  # noqa: E402

U = load_seed_universe(); SEED = 20260614


def _err(profile: str) -> float:
    """Median relative forecast error across many crypto/stock peeks in a world."""
    errs = []
    for sd in range(8):
        w = World.new(U, SEED + sd, profile=profile); e = MarketEngine(w)
        for s in U.stocks[:8]:
            aid = make_asset_id(AssetKind.STOCK, s.symbol)
            p = make_prediction(w, e, aid, DAY)
            true_future = e.price_at(aid, DAY)
            errs.append(abs(p.forecast / true_future - 1))
    return st.median(errs)


def test_calmer_worlds_give_more_accurate_forecasts() -> None:
    calm, normal, apoc = _err("Calm"), _err("Normal"), _err("Apocalyptic")
    assert calm < normal < apoc            # predictability falls -> error grows


def test_prediction_is_deterministic_for_same_tick() -> None:
    w = World.new(U, SEED, profile="Normal"); e = MarketEngine(w)
    aid = make_asset_id(AssetKind.CRYPTO, "BTR")
    a = make_prediction(w, e, aid, DAY)
    b = make_prediction(w, e, aid, DAY)
    assert a.forecast == b.forecast and a.cost == b.cost


def test_cost_higher_for_obscure_and_crypto() -> None:
    w = World.new(U, SEED, profile="Normal")
    big = max(U.stocks, key=lambda s: s.market_cap)
    small = min(U.stocks, key=lambda s: s.market_cap)
    c_big = quote_cost(w, make_asset_id(AssetKind.STOCK, big.symbol), DAY)
    c_small = quote_cost(w, make_asset_id(AssetKind.STOCK, small.symbol), DAY)
    c_crypto = quote_cost(w, make_asset_id(AssetKind.CRYPTO, "BTR"), DAY)
    assert c_small > c_big
    assert c_crypto > c_big
    assert c_big > 0


def test_longer_horizon_costs_more_and_is_fuzzier() -> None:
    w = World.new(U, SEED, profile="Normal"); e = MarketEngine(w)
    aid = make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)
    short = make_prediction(w, e, aid, DAY)
    long = make_prediction(w, e, aid, 10 * DAY)
    assert long.cost > short.cost
    assert long.sigma > short.sigma


# --- Tier 4: horizon-aware confidence + edge-scaled cost --- #

def test_confidence_falls_with_horizon() -> None:
    w = World.new(U, SEED, profile="Normal"); e = MarketEngine(w)
    aid = make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)
    near = make_prediction(w, e, aid, DAY)
    far = make_prediction(w, e, aid, 30 * DAY)
    assert 0 < far.confidence < near.confidence <= 1.0   # a longer peek is less sure


def test_cost_scales_with_world_edge() -> None:
    aid = make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)
    calm = World.new(U, SEED, profile="Calm")
    apoc = World.new(U, SEED, profile="Apocalyptic")
    # a sharper world's peek is worth more, so it costs more for the same asset/horizon
    assert quote_cost(calm, aid, DAY) > quote_cost(apoc, aid, DAY)


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f(); print(f"ok  {n}")
    print("all prediction tests passed")
