"""The blotter (P7): every fill — manual, triggered, liquidation — lands on Portfolio.fills.

Recording happens in the one path every fill takes (execute_order); the two other callers tag
their rows with a `source`. The rows save with the world and old saves load with an empty
blotter. The UI over this is P8; the lifetime sums are P9."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, Order, OrderSide, OrderKind, Fill, fill_action,
    execute_order, place_pending, process_pending, liquidate_for_margin,
    AssetKind, make_asset_id,
)
from trader_pro.core.portfolio import Portfolio  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro import persistence as P  # noqa: E402

U = load_seed_universe()


def _world(cash=100_000.0, seed=20260614, fee_level="off"):
    w = World.new(U, seed, starting_cash=cash)
    w.config.fee_level = fee_level
    MarketEngine(w)            # live prices at tick 0
    return w


def _stock(i=0):
    return make_asset_id(AssetKind.STOCK, U.stocks[i].symbol)


# --- fill_action: the trader's word for what happened --------------------------------------- #

def test_fill_action_reads_the_position_it_hit() -> None:
    assert fill_action(OrderSide.BUY, 0) == "buy"
    assert fill_action(OrderSide.BUY, 10) == "buy"
    assert fill_action(OrderSide.BUY, -10) == "cover"     # includes a cover that flips long
    assert fill_action(OrderSide.SELL, 10) == "sell"      # includes a sell that flips short
    assert fill_action(OrderSide.SELL, 0) == "short"
    assert fill_action(OrderSide.SELL, -10) == "short"


# --- manual fills --------------------------------------------------------------------------- #

def test_manual_fill_writes_one_row_with_the_execution_facts() -> None:
    w = _world(fee_level="medium"); aid = _stock(); px = w.price(aid)
    res = execute_order(w, Order(aid, OrderSide.BUY, 10))
    assert res.filled and res.fill is w.portfolio.fills[-1]
    f = w.portfolio.fills[0]
    assert (f.tick, f.asset_id, f.side, f.action, f.quantity, f.price, f.source) == \
           (0, aid, OrderSide.BUY, "buy", 10, px, "manual")
    assert f.fee == res.fee > 0                          # commission recorded on the row
    assert f.realized_pnl == 0.0                         # opening: nothing closed
    assert f.notional == 10 * px and f.symbol == U.stocks[0].symbol


def test_closing_fill_carries_realized_pnl_gross_of_fee() -> None:
    w = _world(fee_level="medium"); aid = _stock(); px = w.price(aid)
    execute_order(w, Order(aid, OrderSide.BUY, 10))
    w.market.prices[aid] = px * 1.10                      # +10%
    res = execute_order(w, Order(aid, OrderSide.SELL, 10))
    f = w.portfolio.fills[1]
    assert f.action == "sell" and f.source == "manual"
    assert f.realized_pnl == res.realized_pnl > 0        # gross of commission ...
    assert f.fee == res.fee > 0
    assert f.net_pnl == res.realized_pnl - res.fee       # ... net is what hit the tally


def test_short_and_cover_are_named_as_such() -> None:
    w = _world(); aid = _stock()
    execute_order(w, Order(aid, OrderSide.SELL, 5))      # from flat: a short
    execute_order(w, Order(aid, OrderSide.SELL, 5))      # extending it: still a short
    execute_order(w, Order(aid, OrderSide.BUY, 12))      # covers 10 and flips 2 long: a cover
    assert [f.action for f in w.portfolio.fills] == ["short", "short", "cover"]
    assert [f.side for f in w.portfolio.fills] == [OrderSide.SELL, OrderSide.SELL, OrderSide.BUY]


def test_rejected_order_writes_nothing() -> None:
    w = _world(cash=100.0); aid = _stock()
    res = execute_order(w, Order(aid, OrderSide.BUY, 1e9))
    assert not res.filled and res.fill is None
    assert w.portfolio.fills == []
    assert not execute_order(w, Order(aid, OrderSide.BUY, -1)).filled
    assert not execute_order(w, Order("STOCK:NOPE", OrderSide.BUY, 1)).filled
    assert w.portfolio.fills == []


def test_blotter_net_sums_to_the_realized_tally() -> None:
    """The invariant P9 will lean on: Σ net_pnl over the blotter == Portfolio.realized_pnl."""
    w = _world(fee_level="high"); a, b = _stock(0), _stock(1)
    pa, pb = w.price(a), w.price(b)
    execute_order(w, Order(a, OrderSide.BUY, 20))
    execute_order(w, Order(b, OrderSide.SELL, 15))
    w.market.prices[a] = pa * 0.9; w.market.prices[b] = pb * 1.2
    execute_order(w, Order(a, OrderSide.SELL, 30))       # sell 20, flip 10 short
    execute_order(w, Order(b, OrderSide.BUY, 15))        # cover at a loss
    w.market.prices[a] = pa * 0.7
    execute_order(w, Order(a, OrderSide.BUY, 10))        # cover the short at a gain
    assert len(w.portfolio.fills) == 5
    assert sum(f.net_pnl for f in w.portfolio.fills) == \
           __import__("pytest").approx(w.portfolio.realized_pnl)


# --- the other two sources ------------------------------------------------------------------ #

def test_fired_resting_orders_are_tagged_by_kind() -> None:
    w = _world(); aid = _stock(); px = w.price(aid)
    place_pending(w, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)    # already in the money
    place_pending(w, aid, OrderSide.SELL, 1, OrderKind.STOP, px * 1.5)    # fires on the fall
    results = process_pending(w)
    assert [r.filled for r in results] == [True, True]
    assert [f.source for f in w.portfolio.fills] == ["limit", "stop"]
    assert [f.action for f in w.portfolio.fills] == ["buy", "sell"]
    assert results[0].fill is w.portfolio.fills[0]


def test_cancelled_at_trigger_writes_nothing() -> None:
    w = _world(cash=1_000.0); aid = _stock(); px = w.price(aid)
    place_pending(w, aid, OrderSide.BUY, 1e9, OrderKind.STOP, px * 0.5)
    results = process_pending(w)
    assert len(results) == 1 and not results[0].filled and results[0].fill is None
    assert w.portfolio.fills == []


def test_liquidation_is_tagged_and_carries_its_loss() -> None:
    w = _world(cash=10_000.0); aid = _stock(); price = w.price(aid)
    execute_order(w, Order(aid, OrderSide.SELL, 18_000.0 / price))       # big leveraged short
    w.market.prices[aid] = price * 2.0                                  # rips against it
    closures = liquidate_for_margin(w)
    assert closures
    forced = w.portfolio.fills[1:]
    assert len(forced) == len(closures)
    assert all(f.source == "liquidation" and f.action == "cover" for f in forced)
    assert all(f.realized_pnl < 0 for f in forced)
    assert all(c.fill is f for c, f in zip(closures, forced))


# --- through the shared advance seam ------------------------------------------------------- #

def test_advance_records_fills_in_order_with_the_advance_tick() -> None:
    app = TraderApp(world=_world())
    aid = _stock(); px = app.world.price(aid)
    place_pending(app.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)
    app._advance(3)
    f = app.world.portfolio.fills[-1]
    assert f.source == "limit" and f.tick == app.world.market.tick_index == 3


# --- persistence ---------------------------------------------------------------------------- #

def test_fill_round_trips_through_dict() -> None:
    f = Fill(tick=7, asset_id="STOCK:ZZ", side=OrderSide.SELL, action="short", quantity=2.5,
             price=10.0, fee=0.03, realized_pnl=-1.5, source="stop")
    d = f.to_dict()
    assert d["side"] == "sell" and set(d) == {"tick", "asset_id", "side", "action", "quantity",
                                             "price", "fee", "realized_pnl", "source"}
    assert Fill.from_dict(d) == f


def test_portfolio_saves_and_loads_the_blotter() -> None:
    w = _world(fee_level="low"); aid = _stock()
    execute_order(w, Order(aid, OrderSide.BUY, 4))
    execute_order(w, Order(aid, OrderSide.SELL, 4))
    pf2 = Portfolio.from_dict(w.portfolio.to_dict())
    assert pf2.fills == w.portfolio.fills
    assert pf2.realized_pnl == w.portfolio.realized_pnl


def test_back_compat_load_without_fills() -> None:
    # a save written before P7 has no "fills" key: it loads with an empty blotter, and a row
    # written by hand with only the essentials fills in the rest
    pf = Portfolio.from_dict({"cash": 2500.0})
    assert pf.fills == []
    f = Fill.from_dict({"asset_id": "STOCK:A", "side": "sell", "quantity": 1, "price": 2.0})
    assert (f.tick, f.action, f.fee, f.realized_pnl, f.source) == (0, "sell", 0.0, 0.0, "manual")


def test_blotter_survives_a_save_file(tmp_path) -> None:
    w = _world(); aid = _stock()
    execute_order(w, Order(aid, OrderSide.BUY, 3))
    P.save_game(w, tmp_path / "blotter.json")
    w2 = P.load_game(tmp_path / "blotter.json", U)
    assert w2.portfolio.fills == w.portfolio.fills
    assert w2.portfolio.fills[0].side is OrderSide.BUY   # the enum, not the string, after a load
