"""World, orders, and serialization tests (V0.2)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, Order, OrderSide, execute_order,
    AssetKind, make_asset_id, save_world, load_world,
)

UNIVERSE = load_seed_universe()


def _a_stock_id() -> str:
    return make_asset_id(AssetKind.STOCK, UNIVERSE.stocks[0].symbol)


def test_new_world_is_fully_priced_at_tick_zero() -> None:
    w = World.new(UNIVERSE, world_seed=1, starting_cash=2500.0)
    assert w.market.tick_index == 0
    assert w.portfolio.cash == 2500.0
    assert len(w.market.prices) == len(w.asset_ids())
    assert all(p > 0 for p in w.market.prices.values())


def test_buy_then_sell_updates_cash_and_realized_pnl() -> None:
    w = World.new(UNIVERSE, world_seed=1, starting_cash=100_000.0)
    aid = _a_stock_id()
    price = w.price(aid)

    buy = execute_order(w, Order(aid, OrderSide.BUY, 10))
    assert buy.filled
    assert abs(w.portfolio.cash - (100_000.0 - price * 10)) < 1e-6
    assert w.portfolio.positions[aid].quantity == 10

    sell = execute_order(w, Order(aid, OrderSide.SELL, 4))
    assert sell.filled
    assert w.portfolio.positions[aid].quantity == 6
    # No price movement yet (V0.2), so realized P&L is ~0.
    assert abs(sell.realized_pnl) < 1e-6


def test_overspend_rejected_but_small_short_allowed() -> None:
    w = World.new(UNIVERSE, world_seed=1, starting_cash=50.0)
    aid = _a_stock_id()
    # Buying 100k of anything on $50 blows the margin limit -> rejected.
    assert not execute_order(w, Order(aid, OrderSide.BUY, 100_000)).filled
    # A tiny short IS allowed now (V1.3): proceeds + equity cover initial margin.
    res = execute_order(w, Order(aid, OrderSide.SELL, 1))
    assert res.filled
    assert w.portfolio.positions[aid].quantity == -1   # negative = short
    # But shorting 100k is far beyond buying power -> rejected.
    assert not execute_order(w, Order(aid, OrderSide.SELL, 100_000)).filled


def test_equity_conserved_by_trading() -> None:
    w = World.new(UNIVERSE, world_seed=1, starting_cash=100_000.0)
    before = w.equity()
    execute_order(w, Order(_a_stock_id(), OrderSide.BUY, 25))
    # Buying at market with no spread/fees leaves equity unchanged.
    assert abs(w.equity() - before) < 1e-6


def test_save_load_round_trip() -> None:
    w = World.new(UNIVERSE, world_seed=42, profile="Volatile", starting_cash=2500.0)
    execute_order(w, Order(_a_stock_id(), OrderSide.BUY, 3))
    w.advance_tick(120)

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "save.world"
        save_world(w, p)
        w2 = load_world(p, UNIVERSE)

    assert w2.config.world_seed == 42
    assert w2.config.profile == "Volatile"
    assert w2.market.tick_index == 120
    assert w2.to_dict() == w.to_dict()  # full state preserved


# --- Tier 4: bond coupon income --- #

def test_bond_coupons_pay_income_to_cash() -> None:
    from trader_pro.core.portfolio import Position
    w = World.new(UNIVERSE, world_seed=20260614, starting_cash=100_000.0)
    aid = make_asset_id(AssetKind.BOND, "GOVT-30Y")
    b = w.meta_of(aid)
    w.portfolio.positions[aid] = Position(quantity=10.0, avg_cost=w.price(aid))
    cash0 = w.portfolio.cash
    credited = w.accrue_coupons(365 * 1440)                       # one year
    assert abs(credited - b.coupon_rate * b.face_value * 10) < 1e-6   # long earns the coupon
    assert abs(w.portfolio.cash - cash0 - credited) < 1e-6           # ...into cash


def test_coupons_only_bonds_shorts_pay() -> None:
    from trader_pro.core.portfolio import Position
    w = World.new(UNIVERSE, world_seed=20260614, starting_cash=100_000.0)
    baid = make_asset_id(AssetKind.BOND, "GOVT-30Y")
    saidd = _a_stock_id()
    w.portfolio.positions[baid] = Position(quantity=-5.0, avg_cost=w.price(baid))   # short bond
    w.portfolio.positions[saidd] = Position(quantity=100.0, avg_cost=w.price(saidd))  # long stock
    credited = w.accrue_coupons(365 * 1440)
    b = w.meta_of(baid)
    assert credited < 0                                              # a short bond PAYS the coupon
    assert abs(credited - (-5.0) * b.coupon_rate * b.face_value) < 1e-6  # stock earns nothing


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all world tests passed")
