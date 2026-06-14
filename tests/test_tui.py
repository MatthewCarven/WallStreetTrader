"""Headless pilot smoke test for the Textual TUI (front-end)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import Input, DataTable  # noqa: E402
from trader_pro.tui import TraderTUI, TradeDialog  # noqa: E402
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

        # Space plays; clock advances
        t0 = app.trader.world.market.tick_index
        await pilot.press("space")
        assert app.playing
        await pilot.pause(0.8)
        assert app.trader.world.market.tick_index > t0
        await pilot.press("space")  # pause

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
        # crypto (12) -> no Next row
        await pilot.press("1")
        assert app._visible()[1] is None

        # speed control
        idx0 = app.speed_idx
        await pilot.press("right_square_bracket")
        assert app.speed_idx == idx0 + 1

        # trade dialog: open for a stock, buy via the dialog
        aid = f"STOCK:{U.stocks[0].symbol}"
        dlg = TradeDialog(aid)
        app.push_screen(dlg)
        await pilot.pause()
        dlg.query_one("#qty", Input).value = "3"
        dlg._act("buy")
        await pilot.pause()
        assert aid in app.trader.world.portfolio.positions
        assert app.trader.world.portfolio.positions[aid].quantity == 3

        # dialog short then it should reflect a negative position on a fresh asset
        aid2 = f"CRYPTO:SLR"
        dlg2 = TradeDialog(aid2)
        app.push_screen(dlg2)
        await pilot.pause()
        dlg2.query_one("#qty", Input).value = "5"
        dlg2._act("short")
        await pilot.pause()
        assert app.trader.world.portfolio.positions[aid2].quantity == -5


def test_tui_smoke() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_tui_smoke()
    print("ok  test_tui_smoke")
    print("all tui tests passed")
