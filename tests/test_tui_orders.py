"""TUI surface for resting stop/limit orders (Slice L4): trade-dialog trigger + OrdersScreen."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import Input, DataTable  # noqa: E402
from trader_pro.tui import TraderTUI, TradeDialog, OrdersScreen  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, OrderSide, OrderKind, place_pending,
)

U = load_seed_universe()


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=100_000.0), universe=U))


def test_infer_kind_truth_table() -> None:
    # a buy below (or sell above) the price is a LIMIT; a buy above (or sell below) is a STOP
    f = TradeDialog._infer_kind
    assert f(OrderSide.BUY, 90, 100) is OrderKind.LIMIT     # buy the dip
    assert f(OrderSide.BUY, 110, 100) is OrderKind.STOP     # breakout entry
    assert f(OrderSide.SELL, 110, 100) is OrderKind.LIMIT   # take profit
    assert f(OrderSide.SELL, 90, 100) is OrderKind.STOP     # stop-loss


async def _scenario() -> None:
    app = _app()
    aid = f"STOCK:{U.stocks[0].symbol}"
    async with app.run_test() as pilot:
        # --- trade dialog rests a stop/limit when the trigger field is filled ---
        b = app.query_one("#board", DataTable); b.focus(); b.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")                       # open TradeDialog on row 0
        await pilot.pause()
        dlg = app.screen
        assert dlg.__class__.__name__ == "TradeDialog"
        price = app.trader.world.price(dlg.aid)
        dlg.query_one("#qty", Input).value = "5"
        dlg.query_one("#trigger", Input).value = f"{price * 0.9:.4f}"   # buy below => LIMIT
        dlg._act("buy")                                  # rests + dismisses
        await pilot.pause()
        assert len(app.screen_stack) == 1                # dialog closed
        pending = app.trader.world.portfolio.pending
        assert len(pending) == 1
        o = pending[0]
        assert (o.side, o.kind, o.quantity) == (OrderSide.BUY, OrderKind.LIMIT, 5)

        # ambient count shows up in the port panel
        app._refresh()
        assert "resting order" in str(app.query_one("#port").renderable)

        # --- OrdersScreen lists them and cancels ---
        place_pending(app.trader.world, aid, OrderSide.SELL, 3, OrderKind.STOP, price * 0.8)
        app.action_orders()
        await pilot.pause()
        scr = app.screen
        assert isinstance(scr, OrdersScreen)
        assert scr.query_one("#orders-tbl", DataTable).row_count == 2
        scr._cur = str(o.id)                             # highlight order #1
        scr.action_cancel_order()                        # cancel it
        await pilot.pause()
        remaining = app.trader.world.portfolio.pending
        assert len(remaining) == 1 and remaining[0].id != o.id
        assert scr.query_one("#orders-tbl", DataTable).row_count == 1
        scr.dismiss(None)
        await pilot.pause()
        assert len(app.screen_stack) == 1


def test_tui_orders() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_infer_kind_truth_table()
    test_tui_orders()
    print("ok  test_tui_orders")
