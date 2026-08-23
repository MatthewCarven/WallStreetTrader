"""P4 — the board's price flash: cells tint green/red on a tick move, then fade.

Two halves, mirroring how the slice is built:

* the **pure** half (`PriceFlash`, `blend_hex`, `row_background`) needs no Qt and no clock — every
  method takes `now`, so the fade is exercised at exact instants instead of by sleeping;
* the **wiring** half drives a real `TraderGUI` in a subprocess (PySide6's shiboken import hook
  and Textual's lazy modules must not share an interpreter — see test_gui_smoke.py).

The behaviours worth defending are the *quiet* ones: a first sighting, a paged-back-to row, a
loaded world and a re-enabled toggle must all stay dark. A flash means "this price just moved on
your screen", and the moment it means anything looser the board becomes a disco.
"""
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Pure — no Qt required
# --------------------------------------------------------------------------- #

def test_blend_hex_interpolates_and_clamps():
    from trader_pro.gui.model import BG, GREEN, blend_hex

    assert blend_hex(BG, GREEN, 0.0) == BG          # both endpoints exact: the fade has to land
    assert blend_hex(BG, GREEN, 1.0) == GREEN       # on the untinted cell colour, not near it
    assert blend_hex(BG, GREEN, -5.0) == BG         # clamped, never a negative channel
    assert blend_hex(BG, GREEN, 5.0) == GREEN
    assert blend_hex("#000000", "#ffffff", 0.5) == "#808080"


def test_row_background_follows_the_alternating_rows():
    from trader_pro.gui.model import BG, PANEL, row_background

    # Qt paints even rows the base colour and odd rows the alternate one; a flash blends up from
    # whichever it is, so the tail of the fade meets the real cell instead of snapping.
    assert row_background(0) == BG and row_background(2) == BG
    assert row_background(1) == PANEL and row_background(3) == PANEL


def test_first_sighting_never_flashes():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash()
    f.update({"CRYPTO:BTR": 100.0}, 0.0)
    assert f.direction("CRYPTO:BTR", 0.0) == 0
    assert f.alpha("CRYPTO:BTR", 0.0) == 0.0
    assert not f.live(0.0)


def test_direction_and_that_an_unchanged_price_is_silent():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash()
    f.update({"A": 10.0, "B": 10.0, "C": 10.0}, 0.0)
    f.update({"A": 11.0, "B": 9.0, "C": 10.0}, 1.0)
    assert f.direction("A", 1.0) == 1
    assert f.direction("B", 1.0) == -1
    assert f.direction("C", 1.0) == 0           # equal price => no flash, not a zero-length one


def test_alpha_decays_linearly_and_stops_at_zero():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash(duration=1.0)
    f.update({"A": 10.0}, 0.0)
    f.update({"A": 11.0}, 0.0)
    assert f.alpha("A", 0.0) == pytest.approx(1.0)
    assert f.alpha("A", 0.25) == pytest.approx(0.75)
    assert f.alpha("A", 0.5) == pytest.approx(0.5)
    assert f.alpha("A", 1.0) == 0.0
    assert f.alpha("A", 99.0) == 0.0            # long past the end: floored, never negative
    assert f.live(0.5) and not f.live(1.0)


def test_a_second_move_restarts_the_fade():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash(duration=1.0)
    f.update({"A": 10.0}, 0.0)
    f.update({"A": 11.0}, 0.0)
    f.update({"A": 12.0}, 0.6)                  # ticks again while the first flash is half-faded
    assert f.alpha("A", 0.6) == pytest.approx(1.0)


def test_tint_blends_toward_pnl_semantics_and_returns_none_when_dark():
    from trader_pro.gui.model import BG, FLASH_PEAK, GREEN, RED, PriceFlash, blend_hex

    f = PriceFlash(duration=1.0)
    f.update({"UP": 10.0, "DOWN": 10.0}, 0.0)
    f.update({"UP": 11.0, "DOWN": 9.0}, 0.0)
    assert f.tint("UP", 0.0, BG) == blend_hex(BG, GREEN, FLASH_PEAK)
    assert f.tint("DOWN", 0.0, BG) == blend_hex(BG, RED, FLASH_PEAK)
    assert f.tint("UP", 0.5, BG) == blend_hex(BG, GREEN, FLASH_PEAK * 0.5)
    assert f.tint("UP", 1.0, BG) is None         # faded out => don't paint at all
    assert f.tint("NEVER-SEEN", 0.0, BG) is None


def test_the_flash_peaks_short_of_the_full_colour():
    """A saturated cell would drown the pale phosphor digits for a third of a second."""
    from trader_pro.gui.model import BG, FLASH_PEAK, GREEN, PriceFlash

    assert 0.0 < FLASH_PEAK < 1.0
    f = PriceFlash()
    f.update({"A": 1.0}, 0.0)
    f.update({"A": 2.0}, 0.0)
    assert f.tint("A", 0.0, BG) != GREEN


def test_an_asset_off_the_board_is_forgotten_so_paging_back_is_quiet():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash()
    f.update({"A": 10.0, "B": 10.0}, 0.0)
    f.update({"B": 10.0}, 1.0)                  # page away from A
    f.update({"A": 99.0, "B": 10.0}, 2.0)       # …and back, at a wildly different price
    assert f.direction("A", 2.0) == 0, "paging back to a moved asset flashed it"


def test_expired_and_departed_flashes_are_pruned():
    """Left alone, the hit dict would grow for the whole session."""
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash(duration=1.0)
    f.update({"A": 10.0, "B": 10.0}, 0.0)
    f.update({"A": 11.0, "B": 11.0}, 0.0)
    assert len(f._hits) == 2
    f.update({"A": 11.0}, 0.1)                  # B leaves the board while still flashing
    assert set(f._hits) == {"A"}
    f.update({"A": 11.0}, 5.0)                  # A's flash has long since faded
    assert f._hits == {}


def test_clear_drops_the_baseline_too():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash()
    f.update({"A": 10.0}, 0.0)
    f.update({"A": 11.0}, 0.0)
    f.clear()
    assert not f.live(0.0)
    f.update({"A": 50.0}, 1.0)                  # first sighting again, however far the price moved
    assert f.direction("A", 1.0) == 0


def test_zero_duration_cannot_divide_by_zero():
    from trader_pro.gui.model import PriceFlash

    f = PriceFlash(duration=0.0)
    f.update({"A": 10.0}, 0.0)
    f.update({"A": 11.0}, 0.0)
    assert 0.0 <= f.alpha("A", 0.0) <= 1.0      # settings are user-editable; nothing may raise


def test_price_column_is_derived_from_board_columns():
    from trader_pro.gui.model import BOARD_COLUMNS, PRICE_COLUMN

    assert BOARD_COLUMNS[PRICE_COLUMN][0] == "price"


# --------------------------------------------------------------------------- #
# Wiring — a real window, in a subprocess
# --------------------------------------------------------------------------- #

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not installed", allow_module_level=True)

_FLASH = textwrap.dedent(
    """
    import os, time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp
    from trader_pro.core import World, load_seed_universe
    from trader_pro.gui.app import TraderGUI
    from trader_pro.gui import model as M
    from trader_pro.gui.settings import get_setting

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()

    def fresh(seed=1):
        return TraderApp(World.new(uni, world_seed=seed, profile="Normal", starting_cash=5000.0),
                         universe=uni)

    gui = TraderGUI(fresh())
    gui.autosave_enabled = False
    m = gui.board_model

    def bg(row, col=M.PRICE_COLUMN):
        c = m.data(m.index(row, col), Qt.BackgroundRole)
        return None if c is None else c.name()

    def dark(model=None):
        mm = model or m
        return all(mm.data(mm.index(r, M.PRICE_COLUMN), Qt.BackgroundRole) is None
                   for r in range(mm.rowCount()))

    def channels(name):
        return [int(name[i:i + 2], 16) for i in (1, 3, 5)]

    # --- a quiet board paints nothing ---------------------------------------------------------
    assert m.rowCount() > 1
    assert dark(), "a board that has not ticked is lit"
    assert m.repaint_flashes() is False, "nothing is flashing, but the timer repainted anyway"
    print("quiet at boot ok")

    # --- a market move lights the Price column, and only the Price column ----------------------
    gui._advance_now(20)
    lit = [r for r in range(m.rowCount()) if bg(r) is not None]
    assert lit, "prices moved and nothing flashed"
    for r in lit:
        for col in range(m.columnCount()):
            if col != M.PRICE_COLUMN:
                assert bg(r, col) is None, f"column {col} painted a background"
    assert m.repaint_flashes() is True
    print("price column only ok -", len(lit), "rows")

    # --- the tint reads as its direction, and sits between the row's own background and the
    #     semantic colour (an exact match is not assertable: data() reads the clock itself) -----
    now = time.monotonic()
    seen = set()
    for r in lit:
        d = m.flash.direction(m.aids[r], now)
        assert d in (1, -1)
        seen.add(d)
        red, green, _blue = channels(bg(r))
        base_r, base_g, _b = channels(M.row_background(r))
        if d > 0:
            assert green > red and green > base_g, f"an up-tick did not read green: {bg(r)}"
        else:
            assert red > green and red > base_r, f"a down-tick did not read red: {bg(r)}"
    assert seen == {1, -1}, f"only one direction occurred, so the other is untested: {seen}"
    print("tint direction ok")

    # --- P&L semantics, not the accent: a blue theme still flashes green and red ---------------
    gui.set_accent("#3b82f6")
    gui._advance_now(20)
    now = time.monotonic()
    for r in range(m.rowCount()):
        d = m.flash.direction(m.aids[r], now)
        if not d:
            continue
        red, green, blue = channels(bg(r))
        assert blue < max(red, green), f"the flash followed the blue accent: {bg(r)}"
    gui.set_accent(None)
    print("semantics ok")

    # --- it fades all the way out, on wall-clock, with the market paused -----------------------
    gui._advance_now(20)
    assert not dark()
    time.sleep(M.FLASH_SECS + 0.15)
    assert dark(), "a flash outlived its duration"
    assert m.repaint_flashes() is False
    print("fade ok")

    # --- the fade has its own timer, because the market timer stops when you pause -------------
    assert gui._flash_timer.isActive() and gui._flash_timer.interval() == M.FLASH_MS
    assert gui._timer.interval() == M.TIMER_MS
    assert gui._flash_timer.interval() < gui._timer.interval()
    gui._on_flash_timer()                       # guarded slot: must never raise
    print("timer ok")

    # --- swapping worlds must not flash the whole board ----------------------------------------
    gui._advance_now(20)
    gui.trader.start_world(World.new(uni, world_seed=99, profile="Normal", starting_cash=5000.0))
    gui._after_world_swap("test swap")
    assert dark(), "a loaded world lit up the board"
    print("world swap ok")

    # --- switching views / paging is silent ----------------------------------------------------
    gui._advance_now(20)
    time.sleep(M.FLASH_SECS + 0.15)
    gui.view_crypto()
    assert dark(), "changing view flashed"
    gui.view_stocks()
    gui._advance_now(20)
    gui.view_crypto()                           # back to rows last seen at a different price
    assert dark(), "paging back flashed"
    print("views ok")

    # --- refresh() asks for a background repaint, so the first frame of a flash is not owed to
    #     the 60 ms timer catching up ----------------------------------------------------------
    roles = []
    conn = m.dataChanged.connect(lambda _tl, _br, r: roles.append(list(r)))
    m.refresh()
    m.dataChanged.disconnect(conn)
    assert roles and any(Qt.BackgroundRole in batch for batch in roles),         f"refresh() repainted without the background role: {roles}"
    print("refresh roles ok")

    # --- the painter's own guard: flipping the flag darkens a *live* flash on the spot ---------
    # set_price_flash() also clears the tracker, so poke the model directly or this guard would
    # be covered only by its neighbours and could rot into a no-op unnoticed.
    gui._advance_now(20)
    assert not dark()
    m.flash_on = False
    assert dark(), "the painter ignored flash_on and kept tinting a live flash"
    m.flash_on = True
    assert not dark(), "the painter stayed dark after the flag came back"
    print("painter guard ok")

    # --- the toggle: off is dark, and back on does not replay the backlog ----------------------
    gui.view_watch()
    gui._advance_now(20)
    gui.set_price_flash(False)
    assert dark()
    assert m.repaint_flashes() is False
    assert get_setting("price_flash") is False, "the toggle was not persisted"
    gui._advance_now(20)                        # the market keeps moving while it is off
    assert dark(), "a disabled flash still painted"
    gui.set_price_flash(True)
    assert dark(), "re-enabling replayed the backlog"
    gui._advance_now(20)
    assert not dark(), "re-enabling left the flash dead"
    print("toggle ok")

    # --- and it is remembered at next launch ---------------------------------------------------
    gui.set_price_flash(False)
    gui.close()
    again = TraderGUI(fresh())
    again.autosave_enabled = False
    assert again.price_flash is False and again.board_model.flash_on is False
    assert again.act_flash.isChecked() is False, "the menu checkmark forgot the preference"
    again._advance_now(20)
    assert dark(again.board_model)
    again.close()
    print("persistence ok")

    print("FLASH OK")
    """
)


def test_price_flash_wiring_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", _FLASH],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "FLASH OK" in proc.stdout, detail
