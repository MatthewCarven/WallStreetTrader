"""P4b — the price flash in the TUI.

The GUI got this in P4; the TUI got it once it turned out to be the front-end actually being
played. The *mechanism* is shared (`trader_pro.flash.PriceFlash`) and already has its own tests,
so this file is about the terminal half: that the tint lands on the right cells, fades onto the
right background, survives a rebuilt table, and stays quiet when it should.

Timing is driven, never waited on. `pilot.pause()` can eat most of a second of wall-clock — long
enough for a 0.7s flash to expire mid-test — so every fade assertion passes an explicit `now` to
`_paint_flashes` instead of sleeping. That is exactly what the clock injection is for.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.coordinate import Coordinate            # noqa: E402
from textual.widgets import DataTable                # noqa: E402

from trader_pro.cli import TraderApp                 # noqa: E402
from trader_pro.core import World, load_seed_universe  # noqa: E402
from trader_pro.flash import FLASH_SECS              # noqa: E402
from trader_pro.tui import TraderTUI                 # noqa: E402

U = load_seed_universe()


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 7, profile="Normal", starting_cash=25_000.0), universe=U))


def _bg(table: DataTable, row: int, col: int) -> str | None:
    """The background hex a cell is currently wearing, or None if it is untinted."""
    style = str(table.get_cell_at(Coordinate(row, col)).style or "")
    return style.replace("on ", "") if style.startswith("on ") else None


def _channels(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _fade_timer(app: TraderTUI):
    """The interval that drives the fade, or None if nobody armed one."""
    for timer in getattr(app, "_timers", ()):
        if getattr(timer._callback, "__name__", "") == "_tick_flash":
            return timer
    return None


# --------------------------------------------------------------------------- #

def test_the_mechanism_is_shared_with_the_gui():
    """One implementation, two front-ends — the point of moving it to `trader_pro.flash`."""
    from trader_pro import flash
    from trader_pro.gui import model

    assert model.PriceFlash is flash.PriceFlash
    assert model.blend_hex is flash.blend_hex
    # The P&L hexes are duplicated on purpose (flash.py must not import a front-end package),
    # so pin the copies together or they will drift the first time someone retunes the green.
    assert flash.UP == model.GREEN and flash.DOWN == model.RED


def test_row_bases_fall_back_rather_than_raise():
    """Textual's component classes are not ours. If they move, the fade lands a couple of
    channels off — it does not take the board down."""
    class Broken:
        background_colors = property(lambda self: 1 / 0)

    assert TraderTUI._row_bases_from(Broken()) == ("#07120b", "#07120b")


async def _scenario_flash() -> None:
    app = _app()
    async with app.run_test(size=(150, 42)) as pilot:
        table = app.query_one("#board", DataTable)
        col = app._price_col()
        assert col is not None

        # --- the fade endpoints come from the table's real zebra colours ---------------------
        even, odd = app._row_bases
        assert even != odd, "both row parities fade onto the same colour; zebra was not read"
        for base in (even, odd):
            assert len(base) == 7 and base.startswith("#")
        assert app._flash_on is True                      # default on, no setting written

        # --- a board that has not ticked is dark ---------------------------------------------
        assert app._price_cells, "no price cells were tracked"
        assert not app._tinted
        assert all(_bg(table, r, col) is None for r in sorted(app._price_cells))

        # --- a day passes: every price moves, every price cell lights -------------------------
        app.trader._advance(1440)
        app._refresh()
        now = time.monotonic()
        rows = sorted(app._price_cells)
        assert app._tinted, "prices moved and nothing was tinted"
        seen = set()
        for row in rows:
            aid, _price, _plain = app._price_cells[row]
            direction = app._flash.direction(aid, now)
            tint = _bg(table, row, col)
            assert tint is not None, f"row {row} moved but stayed dark"
            seen.add(direction)
            red, green, _blue = _channels(tint)
            base_r, base_g, _b = _channels(app._row_bases[row % 2])
            if direction > 0:
                assert green > red and green > base_g, f"up-tick not green: {tint}"
            else:
                assert red > green and red > base_r, f"down-tick not red: {tint}"
        assert seen == {1, -1}, f"only one direction occurred, so the other is untested: {seen}"

        # --- each row fades onto the background *it* sits on -----------------------------------
        # Pinned by exact value, because the two zebra shades differ by a handful of channels:
        # blend every row from the even one and the picture still looks right while being wrong.
        # The fade timer is paused for this, or its own repaint lands between paint and read.
        timer = _fade_timer(app)
        assert timer is not None, "nothing is driving the fade between market ticks"
        timer.pause()
        try:
            frozen = now + FLASH_SECS * 0.4
            app._paint_flashes(table, frozen)
            for row in rows:
                aid, _price, _plain = app._price_cells[row]
                assert _bg(table, row, col) == app._flash.tint(aid, frozen, app._row_bases[row % 2]),                     f"row {row} did not fade onto its own zebra shade"
        finally:
            timer.resume()

        # --- and only the Price column ---------------------------------------------------------
        for row in rows[:5]:
            for other in range(len(app._visible_columns())):
                if other != col:
                    assert _bg(table, row, other) is None, f"column {other} was painted"

        # --- the fade is driven by the clock it is handed --------------------------------------
        app._paint_flashes(table, now + FLASH_SECS * 0.5)
        half = _bg(table, rows[0], col)
        app._paint_flashes(table, now + FLASH_SECS * 0.9)
        late = _bg(table, rows[0], col)
        assert half and late and half != late, "the tint did not change as the clock advanced"
        app._paint_flashes(table, now + FLASH_SECS + 0.1)
        assert all(_bg(table, r, col) is None for r in rows), "a flash outlived its duration"
        assert not app._tinted, "_tinted still names rows that are no longer painted"

        # --- the fade advances with nobody calling it ------------------------------------------
        app.trader._advance(1440)
        app._refresh()
        before = _bg(table, rows[0], col)
        assert before is not None
        await asyncio.sleep(0.15)                         # ~2 beats of the 60ms timer
        assert _bg(table, rows[0], col) != before,             "the tint sat still: the fade is not being driven between market ticks"

        # --- switching views is silent (the baseline is per-asset, and they are new here) ------
        app.trader._advance(60)
        app._refresh()
        await pilot.press("1")                            # crypto
        await pilot.press("2")                            # stocks
        app._refresh()
        assert all(_bg(table, r, col) is None for r in sorted(app._price_cells)), \
            "changing view flashed the whole board"

        # --- the price column can be hidden (Ctrl+2); nothing may break --------------------
        app.col_visible["price"] = False
        app._rebuild_board_columns()
        app.trader._advance(1440)
        app._refresh()
        assert app._price_col() is None
        assert not app._price_cells and not app._tinted
        app.col_visible["price"] = True
        app._rebuild_board_columns()
        app._refresh()

        # --- switched off: nothing is tracked and nothing is painted -------------------------
        app._flash_on = False
        app._flash.clear()
        app.trader._advance(1440)
        app._refresh()
        assert not app._price_cells, "a disabled flash still tracked cells"
        col = app._price_col()
        assert all(_bg(table, r, col) is None for r in range(min(5, table.row_count)))
        app._tick_flash()                                 # must be a no-op, not a crash


def test_price_flash_in_the_tui():
    asyncio.run(_scenario_flash())


async def _scenario_setting(tmp_settings: Path) -> None:
    app = _app()
    async with app.run_test(size=(150, 42)) as pilot:
        assert app._flash_on is False, "the GUI's Appearance ▸ Price flash toggle was ignored"
        app.trader._advance(1440)
        app._refresh()
        assert not app._price_cells and not app._tinted
        await pilot.pause()


def test_the_gui_toggle_governs_the_tui_too(tmp_path, monkeypatch):
    """One preference file, both front-ends — turning it off in the GUI turns it off here."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({"price_flash": False}), encoding="utf-8")
    monkeypatch.setenv("TRADER_PRO_SETTINGS_DIR", str(settings_dir))
    asyncio.run(_scenario_setting(settings_dir))
