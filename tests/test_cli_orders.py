"""CLI surface for resting stop/limit orders (Slice L3): limit / stop / orders / cancel."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402

U = load_seed_universe()


def _app(cash=100_000.0):
    return TraderApp(World.new(U, world_seed=20260614, profile="Normal", starting_cash=cash), universe=U)


def test_limit_command_rests_order() -> None:
    app = _app()
    px = app.world.price("CRYPTO:BTR")
    out = app.execute(f"limit BTR buy 5 {px * 0.9:.4f}")
    assert "resting order #1" in out
    pending = app.world.portfolio.pending
    assert len(pending) == 1
    o = pending[0]
    assert (o.asset_id, o.kind.value, o.side.value, o.quantity) == ("CRYPTO:BTR", "limit", "buy", 5)


def test_at_sign_and_dollar_amount_parse() -> None:
    app = _app()
    # '@' is optional sugar; a $amount converts at the *trigger* price
    assert app.execute("limit BTR buy $1000 @ 100")
    o = app.world.portfolio.pending[-1]
    assert abs(o.quantity - 10.0) < 1e-9            # 1000 / 100


def test_orders_lists_and_cancel_by_id() -> None:
    app = _app()
    app.execute("limit BTR buy 5 100")
    app.execute("stop BTR sell 3 50")
    listing = app.execute("orders")
    assert "limit" in listing and "stop" in listing
    assert "cancelled #2" in app.execute("cancel 2")
    assert len(app.world.portfolio.pending) == 1
    assert "#2" in app.execute("cancel 2")          # already gone -> "no resting order #2"


def test_cancel_all() -> None:
    app = _app()
    app.execute("limit BTR buy 5 100")
    app.execute("limit BTR buy 5 90")
    assert "cancelled 2" in app.execute("cancel all")
    assert app.world.portfolio.pending == []


def test_resting_order_fills_on_advance() -> None:
    app = _app()
    sym = U.stocks[0].symbol                         # a cheap stock, comfortably affordable
    aid = f"STOCK:{sym}"
    px = app.world.price(aid)
    app.execute(f"limit {sym} buy 4 {px * 1.1:.4f}")  # above price => in the money
    out = app.execute("next 1")
    assert "filled" in out
    assert aid in app.world.portfolio.positions
    assert app.world.portfolio.pending == []


def test_order_command_validation() -> None:
    app = _app()
    assert "usage" in app.execute("limit").lower()
    assert "buy or sell" in app.execute("limit BTR sideways 5 100")
    assert "unknown symbol" in app.execute("limit NOPE___ buy 5 100")
    assert "quantity" in app.execute("limit BTR buy all 100")     # 'all' refused for resting
    assert "positive" in app.execute("stop BTR buy 5 0")          # trigger must be > 0
    assert app.world.portfolio.pending == []                      # nothing rested on any rejection
