"""P18 — the board's change columns stay honest on a young world.

Every lookback clamps to tick 0 before the world is old enough for it, so a 31-minute-old world
printed the *same* number in 1D / 7D / 31D (the D0 00:31 screenshot: BTR -1.46% three times).
Correct, but indistinguishable from a broken column. Each window now shows a dim em dash until
there is real history behind it, and the movers header says what it is actually ranking by.

The `-` is display-only: `_chg1d` (the sort key for movers and the `o` toggle, and the ticker
arrow) still returns change-since-open, because that ordering is genuinely useful on day zero.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable  # noqa: E402
from trader_pro.tui import TraderTUI, _pct_cell  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402


U = load_seed_universe()
DASH = "—"


def _app(minutes: int) -> TraderTUI:
    app = TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Volatile", starting_cash=10_000.0), universe=U))
    if minutes:
        app.trader._advance(minutes)
    return app


def _col(app: TraderTUI, table: DataTable, row: int, col_id: str) -> str:
    """The plain text of one board cell, found by column id (columns can be hidden)."""
    idx = [c[0] for c in app._visible_columns()].index(col_id)
    return table.get_row_at(row)[idx].plain.strip()


def test_pct_cell_renders_none_as_a_dash() -> None:
    assert _pct_cell(None).plain.strip() == DASH
    assert _pct_cell(1.5).plain.strip() == "+1.50%"
    assert _pct_cell(-1.5).plain.strip() == "-1.50%"


async def _young_world() -> None:
    app = _app(31)                                       # the screenshot's 31-minute-old world
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#board", DataTable)
        for col in ("chg", "chg7d", "chg31d"):
            assert _col(app, table, 0, col) == DASH, f"{col} should be blank on a 31-minute world"

        # the ranking still works — it just isn't a "1D" ranking yet, and the header says so
        await pilot.press("5")                           # movers
        await pilot.pause()
        gainers, losers = app._movers(10)
        assert gainers[0][0] >= gainers[-1][0] and losers[0][0] <= losers[-1][0]
        assert any(chg != 0.0 for chg, _ in gainers)     # real numbers behind the ordering
        hdr = app.query_one("#board", DataTable).get_row_at(0)
        assert "since open" in " ".join(c.plain for c in hdr)


async def _old_world() -> None:
    app = _app(40 * 1440)                                # past a month: every window is real
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#board", DataTable)
        shown = [_col(app, table, 0, c) for c in ("chg", "chg7d", "chg31d")]
        assert all(s.endswith("%") for s in shown), shown
        assert len(set(shown)) == 3                      # …and they disagree, as they should

        await pilot.press("5")                           # movers header reverts to "1D %"
        await pilot.pause()
        hdr = app.query_one("#board", DataTable).get_row_at(0)
        assert "1D %" in " ".join(c.plain for c in hdr)


async def _partial_world() -> None:
    app = _app(2 * 1440)                                 # two days: 1D real, 7D and 31D not yet
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#board", DataTable)
        assert _col(app, table, 0, "chg").endswith("%")
        assert _col(app, table, 0, "chg7d") == DASH
        assert _col(app, table, 0, "chg31d") == DASH


async def _timer_survives_teardown() -> None:
    """The 0.3s interval can fire once after the app is gone; #ticker no longer exists by then
    and `screen_stack` is back to 1, so the modal guard doesn't cover it. It used to raise
    NoMatches and made the suite intermittently red."""
    app = _app(0)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
    assert not app.is_running
    app._on_timer()                                      # must not raise


def test_change_columns_young_world() -> None:
    asyncio.run(_young_world())


def test_change_columns_partial_history() -> None:
    asyncio.run(_partial_world())


def test_change_columns_old_world() -> None:
    asyncio.run(_old_world())


def test_ticker_timer_survives_teardown() -> None:
    asyncio.run(_timer_survives_teardown())


if __name__ == "__main__":
    test_pct_cell_renders_none_as_a_dash()
    test_change_columns_young_world()
    test_change_columns_partial_history()
    test_change_columns_old_world()
    test_ticker_timer_survives_teardown()
    print("all change-column tests passed")
