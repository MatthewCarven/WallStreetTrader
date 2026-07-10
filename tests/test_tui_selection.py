"""The board keeps its highlighted row when time advances (s/h/d) or the clock runs live,
but a view switch still starts at the top. A trade also holds the row: buying pins the asset
into the holdings block at the top, and we don't want that to yank the cursor up to row 0."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable, Input  # noqa: E402
from trader_pro.tui import TraderTUI  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402


U = load_seed_universe()


def _key_at(table: DataTable, row: int) -> str:
    return table.coordinate_to_cell_key((row, 0)).row_key.value


async def _scenario() -> None:
    app = TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=10_000.0), universe=U))
    app.saves_dir = Path(tempfile.mkdtemp())
    async with app.run_test(size=(120, 40)) as pilot:
        board = app.query_one("#board", DataTable)
        board.focus()
        for _ in range(5):
            await pilot.press("down")
        await pilot.pause()
        sel = _key_at(board, board.cursor_row)
        row = board.cursor_row
        assert row == 5

        # stepping time keeps the same row + asset
        for key in ("d", "h", "s"):
            await pilot.press(key)
            await pilot.pause()
            assert board.cursor_row == row, f"{key} moved the cursor row"
            assert _key_at(board, board.cursor_row) == sel, f"{key} moved the selection"
            assert app.cursor_aid == sel

        # letting the clock run live keeps it too
        await pilot.press("space")
        await pilot.pause(1.0)
        await pilot.press("space")
        assert _key_at(board, board.cursor_row) == sel, "live play moved the selection"

        # but switching board view resets to the top
        await pilot.press("2")        # stocks
        await pilot.pause()
        assert board.cursor_row == 0


def test_selection_persists_across_time() -> None:
    asyncio.run(_scenario())


async def _trade_scenario() -> None:
    app = TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=200_000.0), universe=U))
    app.saves_dir = Path(tempfile.mkdtemp())
    async with app.run_test(size=(120, 40)) as pilot:
        board = app.query_one("#board", DataTable)
        board.focus()
        await pilot.press("2")            # stocks view (unowned candidates)
        await pilot.pause()
        for _ in range(6):
            await pilot.press("down")
        await pilot.pause()
        row = board.cursor_row
        bought = _key_at(board, row)
        assert row == 6

        # buy the highlighted row through the dialog
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 2, "dialog did not open"
        app.screen.query_one("#qty", Input).value = "$500"
        await pilot.pause()
        await pilot.press("enter")        # submit buy -> dialog dismisses, app refreshes
        await pilot.pause()
        await pilot.pause()
        assert len(app.screen_stack) == 1, "dialog did not close"

        # the buy filled and the asset is now a holding (which pins it to the top)...
        assert bought in app.trader.world.portfolio.positions, "buy did not fill"
        # ...but the cursor holds its ROW instead of being yanked up to row 0,
        assert board.cursor_row == row, "trade moved the cursor row"
        # and the name line / chart follow whatever asset is under the cursor now.
        assert app.cursor_aid == _key_at(board, board.cursor_row)


def test_selection_holds_row_across_trade() -> None:
    asyncio.run(_trade_scenario())


if __name__ == "__main__":
    test_selection_persists_across_time()
    print("ok  test_selection_persists_across_time")
    test_selection_holds_row_across_trade()
    print("ok  test_selection_holds_row_across_trade")
