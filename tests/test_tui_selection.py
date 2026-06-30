"""The board keeps its highlighted row when time advances (s/h/d) or the clock runs live,
but a view switch still starts at the top."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable  # noqa: E402
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


if __name__ == "__main__":
    test_selection_persists_across_time()
    print("ok  test_selection_persists_across_time")
