"""Regression tests for the V1.6 TUI retro layer: price-chart pane, movers view,
sort-by-%-change toggle, and the scrolling ticker tape."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable, Static  # noqa: E402
from trader_pro.tui import TraderTUI, area_chart, CHART_RANGES  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402


U = load_seed_universe()
BLOCKS = "█▁▂▃▄▅▆▇"


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Volatile", starting_cash=10_000.0), universe=U))


def test_area_chart_shape() -> None:
    """The area chart resamples to `width` columns and draws exactly `height` rows."""
    t = area_chart([1, 2, 3, 4, 5, 4, 3, 2, 1], width=8, height=5, color="green")
    rows = t.plain.split("\n")
    assert len(rows) == 5
    assert all(len(r) == 8 for r in rows)
    assert any(c in t.plain for c in BLOCKS)
    flat = area_chart([3, 3, 3, 3], width=6, height=4, color="red")
    assert len(flat.plain.split("\n")) == 4


async def _scenario() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(4):                       # build some price history
            app.action_day()
        await pilot.pause()

        # ticker tape builds and scrolls
        assert app._ticker_base
        off0 = app._ticker_off
        app._tick_ticker()
        assert app._ticker_off != off0
        assert app.query_one("#ticker", Static).renderable.plain.strip()

        # chart pane tracks the highlighted asset across every range
        await pilot.press("2")                   # stocks
        board = app.query_one("#board", DataTable)
        board.focus(); board.move_cursor(row=0)
        await pilot.pause()
        assert app.cursor_aid
        expected = app.chart_range
        for _ in range(len(CHART_RANGES)):       # cycle through every range and back
            await pilot.press("c")
            await pilot.pause()
            expected = (expected + 1) % len(CHART_RANGES)
            assert app.chart_range == expected
        assert any(c in app.query_one("#chart", Static).renderable.plain for c in BLOCKS)

        # movers view: 2 header rows + 10 gainers + 10 losers, correctly ordered
        await pilot.press("5")
        await pilot.pause()
        assert app.movers and app.view_label == "movers"
        gainers, losers = app._movers(10)
        assert len(gainers) == 10 and len(losers) == 10
        assert gainers[0][0] >= gainers[-1][0]           # gainers descending
        assert losers[0][0] <= losers[-1][0]             # losers: biggest loss first
        assert app.query_one("#board", DataTable).row_count == 22

        # sort toggle orders the board by 1D % (descending)
        await pilot.press("2")                   # back to stocks (clears movers)
        await pilot.pause()
        assert not app.movers
        await pilot.press("o")
        await pilot.pause()
        assert app.sort_by_change
        ids, _ = app._visible()
        chgs = [app._chg1d(a) for a in ids]
        assert chgs == sorted(chgs, reverse=True)
        await pilot.press("o")
        assert not app.sort_by_change

        # timer stays alive while a modal is up (ticker guard, no NoMatches crash)
        board.focus(); board.move_cursor(row=0)
        await pilot.press("enter")               # open the trade dialog
        await pilot.pause(0.5)                    # let the 0.3s timer fire under the modal
        assert len(app.screen_stack) == 2
        app.screen.dismiss()
        await pilot.pause()
        assert len(app.screen_stack) == 1


def test_tui_features() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_area_chart_shape()
    print("ok  test_area_chart_shape")
    test_tui_features()
    print("ok  test_tui_features")
    print("all tui-feature tests passed")
