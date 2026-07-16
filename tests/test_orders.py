"""Resting stop/limit orders — model, placement, cancel, serialization (Slice L1).

Triggering behaviour (process_pending in the advance loop) is covered in test_pending_trigger.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, OrderSide, OrderKind,
    PendingOrder, place_pending, cancel_pending, AssetKind, make_asset_id,
)
from trader_pro.core.portfolio import Portfolio  # noqa: E402

U = load_seed_universe()


def _world(cash=10_000.0, seed=20260614):
    w = World.new(U, seed, starting_cash=cash)
    MarketEngine(w)            # set live prices at tick 0
    return w


def _stock():
    return make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)


def test_place_assigns_incrementing_ids_and_rests() -> None:
    w = _world(); aid = _stock()
    r1 = place_pending(w, aid, OrderSide.BUY, 10, OrderKind.LIMIT, 100.0)
    r2 = place_pending(w, aid, OrderSide.SELL, 5, OrderKind.STOP, 90.0)
    assert r1 and r2
    assert (r1.order.id, r2.order.id) == (1, 2)
    assert w.portfolio.next_order_id == 3
    assert len(w.portfolio.pending) == 2
    assert r1.order.created_tick == w.market.tick_index


def test_placement_validation() -> None:
    w = _world(); aid = _stock()
    assert not place_pending(w, aid, OrderSide.BUY, 0, OrderKind.LIMIT, 100.0)     # qty <= 0
    assert not place_pending(w, aid, OrderSide.BUY, 10, OrderKind.LIMIT, 0.0)      # price <= 0
    assert not place_pending(w, "STOCK:NOPE", OrderSide.BUY, 10, OrderKind.LIMIT, 100.0)  # unknown
    assert w.portfolio.pending == []           # nothing rested on a rejected placement
    assert w.portfolio.next_order_id == 1      # ... and the id counter didn't move


def test_trigger_truth_table() -> None:
    # rise-fills (>=): SELL limit, BUY stop ;  fall-fills (<=): BUY limit, SELL stop
    lim_buy = PendingOrder(1, "X", OrderSide.BUY, 1, OrderKind.LIMIT, 100.0)
    lim_sell = PendingOrder(2, "X", OrderSide.SELL, 1, OrderKind.LIMIT, 100.0)
    stop_buy = PendingOrder(3, "X", OrderSide.BUY, 1, OrderKind.STOP, 100.0)
    stop_sell = PendingOrder(4, "X", OrderSide.SELL, 1, OrderKind.STOP, 100.0)
    assert lim_buy.is_triggered(99) and not lim_buy.is_triggered(101)
    assert lim_sell.is_triggered(101) and not lim_sell.is_triggered(99)
    assert stop_buy.is_triggered(101) and not stop_buy.is_triggered(99)
    assert stop_sell.is_triggered(99) and not stop_sell.is_triggered(101)
    # a price exactly on the trigger counts as crossed for all four
    assert all(o.is_triggered(100.0) for o in (lim_buy, lim_sell, stop_buy, stop_sell))


def test_cancel_removes_and_returns() -> None:
    w = _world(); aid = _stock()
    place_pending(w, aid, OrderSide.BUY, 10, OrderKind.LIMIT, 100.0)
    r2 = place_pending(w, aid, OrderSide.SELL, 5, OrderKind.STOP, 90.0)
    got = cancel_pending(w, r2.order.id)
    assert got is not None and got.id == r2.order.id
    assert len(w.portfolio.pending) == 1
    assert cancel_pending(w, 999) is None      # unknown id is a no-op


def test_serialization_round_trip() -> None:
    w = _world(); aid = _stock()
    place_pending(w, aid, OrderSide.BUY, 10, OrderKind.LIMIT, 100.0)
    place_pending(w, aid, OrderSide.SELL, 5.5, OrderKind.STOP, 90.0)
    pf2 = Portfolio.from_dict(w.portfolio.to_dict())
    assert pf2.next_order_id == 3
    assert len(pf2.pending) == 2
    o = pf2.pending[0]
    assert (o.id, o.asset_id, o.side, o.quantity, o.kind, o.trigger_price) == \
           (1, aid, OrderSide.BUY, 10, OrderKind.LIMIT, 100.0)


def test_back_compat_load_without_pending() -> None:
    # a save blob written before resting orders existed must still load cleanly
    pf = Portfolio.from_dict({"cash": 2500.0})
    assert pf.pending == []
    assert pf.next_order_id == 1
