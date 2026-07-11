"""Headless pilot smoke test for the Textual TUI (front-end)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import Input, DataTable  # noqa: E402
from trader_pro.tui import TraderTUI, TradeDialog, SPEEDS  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402


U = load_seed_universe()


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=100_000.0), universe=U))


async def _scenario() -> None:
    app = _app()
    async with app.run_test() as pilot:
        assert app.query_one("#board", DataTable).row_count > 0

        # command-line buy still works
        app.action_command()
        app.query_one(Input).value = "buy BTR 1"
        await pilot.press("enter")
        await pilot.pause()
        assert "CRYPTO:BTR" in app.trader.world.portfolio.positions

        # Space plays; the clock advances. The default pace is a deliberate 1 sim-minute per real
        # second, so bump to the fastest tier to see movement within a short real-time window, then
        # step back down to the default so the speed-control check below starts from a known index.
        for _ in range(len(SPEEDS) - 1):
            await pilot.press("right_square_bracket")   # -> fastest
        t0 = app.trader.world.market.tick_index
        await pilot.press("space")
        assert app.playing
        await pilot.pause(0.8)
        assert app.trader.world.market.tick_index > t0
        await pilot.press("space")  # pause
        for _ in range(len(SPEEDS) - 1):
            await pilot.press("left_square_bracket")    # back to the default (slowest)
        assert app.speed_idx == 0

        # number keys switch board views
        await pilot.press("1"); assert app.view_label == "crypto"
        await pilot.press("2"); assert app.view_label == "stocks"
        await pilot.press("3"); assert app.view_label == "bonds"
        await pilot.press("4"); assert app.view_label == "watchlist"
        await pilot.press("0"); assert app.view_label == "owned" and app.owned_only

        # pagination: stocks (503) page in 25s with a Next row
        await pilot.press("2")
        ids, label = app._visible()
        assert len(ids) == 25 and label and "page 1/" in label
        first0 = ids[0]
        app.on_data_table_row_selected(
            type("E", (), {"row_key": type("K", (), {"value": "__next__"})()})())
        await pilot.pause()
        ids2, label2 = app._visible()
        assert app.view_page == 1 and "page 2/" in label2 and ids2[0] != first0
        # bonds (22) fit on one page -> no Next row
        await pilot.press("3")
        assert app._visible()[1] is None

        # speed control
        idx0 = app.speed_idx
        await pilot.press("right_square_bracket")
        assert app.speed_idx == idx0 + 1

        # trade dialog opens on a row and the buy logic is correct (driver-dismiss to
        # avoid a run_test pilot quirk where dismiss-via-keypress doesn't settle).
        aid = f"STOCK:{U.stocks[0].symbol}"
        b = app.query_one("#board", DataTable); b.focus(); b.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")                     # open the dialog (RowSelected)
        await pilot.pause()
        assert len(app.screen_stack) == 2
        dlg = app.screen
        assert dlg.__class__.__name__ == "TradeDialog"
        assert abs(dlg._amount("$300") - 300.0 / app.trader.world.price(dlg.aid)) < 1e-9
        assert dlg._amount("5") == 5.0
        dlg.dismiss(); await pilot.pause()             # driver dismiss works cleanly
        assert len(app.screen_stack) == 1

def test_tui_smoke() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_tui_smoke()
    print("ok  test_tui_smoke")
    print("all tui tests passed")
