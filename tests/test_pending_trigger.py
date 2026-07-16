"""Stop/limit triggering in the advance loop (Slice L2).

Model/placement/serialization live in test_orders.py; here we exercise process_pending — the four
trigger directions, the wait-until-crossed case, trigger-time cancellation, and the wiring through
TraderApp._advance (the single path every front-end shares)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, OrderSide, OrderKind,
    place_pending, process_pending, AssetKind, make_asset_id,
)
from trader_pro.cli import TraderApp  # noqa: E402

U = load_seed_universe()


def _world(cash=100_000.0, seed=20260614):
    w = World.new(U, seed, starting_cash=cash)
    MarketEngine(w)            # live prices at tick 0
    return w


def _stock():
    return make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)


def test_each_kind_fires_in_the_right_direction() -> None:
    # trigger placed so is_triggered(current price) is already true → fires on the next process.
    # buy-limit fills as price falls to it (trigger above); sell-limit as it rises (trigger below);
    # buy-stop as it rises (trigger below); sell-stop as it falls (trigger above).
    aid = _stock()
    cases = [
        (OrderSide.BUY, OrderKind.LIMIT, 1.5),
        (OrderSide.SELL, OrderKind.LIMIT, 0.5),
        (OrderSide.BUY, OrderKind.STOP, 0.5),
        (OrderSide.SELL, OrderKind.STOP, 1.5),
    ]
    for side, kind, mult in cases:
        w = _world()
        px = w.price(aid)
        assert place_pending(w, aid, side, 2, kind, px * mult)
        fills = process_pending(w)
        assert len(fills) == 1 and fills[0].filled, (side, kind)
        assert kind.value in fills[0].message           # "limit filled" / "stop filled"
        assert w.portfolio.pending == []                # left the book once fired
        assert aid in w.portfolio.positions             # opened the position (long or short)


def test_waits_until_crossed() -> None:
    w = _world(); aid = _stock(); px = w.price(aid)
    # buy-limit with a trigger well BELOW the current price hasn't been crossed yet
    place_pending(w, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 0.5)
    assert process_pending(w) == []
    assert len(w.portfolio.pending) == 1                # still resting


def test_triggered_but_unaffordable_is_cancelled() -> None:
    w = _world(cash=1_000.0); aid = _stock(); px = w.price(aid)
    # a buy-stop that fires immediately (trigger below price) but for an absurd quantity
    place_pending(w, aid, OrderSide.BUY, 1e9, OrderKind.STOP, px * 0.5)
    fills = process_pending(w)
    assert len(fills) == 1 and not fills[0].filled
    assert "cancelled" in fills[0].message
    assert w.portfolio.pending == []                    # removed, not retried every tick forever
    assert aid not in w.portfolio.positions             # nothing was bought


def test_advance_threads_fills_through_the_shared_path() -> None:
    # integration: TraderApp._advance now returns (events, closures, fills) and fires resting orders
    app = TraderApp(world=_world())
    aid = _stock(); px = app.world.price(aid)
    place_pending(app.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)
    events, closures, fills = app._advance(1)
    assert len(fills) == 1 and fills[0].filled
    assert aid in app.world.portfolio.positions
