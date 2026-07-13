"""Margin, leverage, shorting, and liquidation tests (V1.3)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, Order, OrderSide, execute_order,
    liquidate_for_margin, AssetKind, make_asset_id,
)
from trader_pro.core.portfolio import INITIAL_MARGIN_RATIO  # noqa: E402

U = load_seed_universe()


def _world(cash=10_000.0, profile="Normal", seed=20260614):
    w = World.new(U, seed, profile=profile, starting_cash=cash)
    MarketEngine(w)            # set live prices at tick 0
    return w


def _stock():
    return make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)


def test_leverage_allows_more_than_cash_up_to_2to1() -> None:
    w = _world(cash=10_000.0)
    aid = _stock(); price = w.price(aid)
    # ~1.8x exposure should be allowed (under 2:1)
    qty = (18_000.0 / price)
    assert execute_order(w, Order(aid, OrderSide.BUY, qty)).filled
    assert w.portfolio.cash < 0                          # borrowed on margin
    assert w.portfolio.gross_exposure(w.price_of) > w.config.starting_cash


def test_over_leverage_rejected() -> None:
    w = _world(cash=10_000.0)
    aid = _stock(); price = w.price(aid)
    qty = (30_000.0 / price)                             # 3x -> over the 2:1 limit
    res = execute_order(w, Order(aid, OrderSide.BUY, qty))
    assert not res.filled and "buying power" in res.message


def test_short_profits_when_price_falls() -> None:
    w = _world(cash=50_000.0)
    aid = _stock()
    assert execute_order(w, Order(aid, OrderSide.SELL, 100)).filled   # open short
    pos = w.portfolio.positions[aid]
    assert pos.quantity == -100
    entry = pos.avg_cost
    # Drop the price by hand and check unrealized P&L is positive.
    w.market.prices[aid] = entry * 0.8
    assert w.portfolio.unrealized_pnl(w.price_of) > 0
    # Cover for a realized gain.
    res = execute_order(w, Order(aid, OrderSide.BUY, 100))
    assert res.filled and res.realized_pnl > 0
    assert aid not in w.portfolio.positions


def test_sell_can_flip_long_to_short() -> None:
    w = _world(cash=100_000.0)
    aid = _stock()
    execute_order(w, Order(aid, OrderSide.BUY, 10))      # long 10
    execute_order(w, Order(aid, OrderSide.SELL, 25))     # sell 25 -> short 15
    assert w.portfolio.positions[aid].quantity == -15


def test_margin_call_liquidates_a_blown_up_short() -> None:
    w = _world(cash=10_000.0)
    aid = _stock(); price = w.price(aid)
    qty = (18_000.0 / price)
    execute_order(w, Order(aid, OrderSide.SELL, qty))    # big leveraged short
    assert not w.portfolio.is_margin_call(w.price_of)
    # Price rips up against the short -> equity collapses -> margin call.
    w.market.prices[aid] = price * 2.0
    assert w.portfolio.is_margin_call(w.price_of)
    closures = liquidate_for_margin(w)
    assert closures
    assert not w.portfolio.is_margin_call(w.price_of)    # cleared after liquidation


def test_margin_call_trims_position_not_nukes_it_on_small_breach() -> None:
    w = _world(cash=10_000.0)
    aid = _stock(); price = w.price(aid)
    execute_order(w, Order(aid, OrderSide.BUY, 19_000.0 / price))   # ~1.9x long
    assert not w.portfolio.is_margin_call(w.price_of)
    q_before = abs(w.portfolio.positions[aid].quantity)
    w.market.prices[aid] = price * 0.60                            # a small adverse move -> slight breach
    assert w.portfolio.is_margin_call(w.price_of)
    closures = liquidate_for_margin(w)
    assert closures and not w.portfolio.is_margin_call(w.price_of)  # breach cured
    assert aid in w.portfolio.positions                            # ...but the holding survives
    assert abs(w.portfolio.positions[aid].quantity) < q_before      # only trimmed, not force-closed


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all margin tests passed")
