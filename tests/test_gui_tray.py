"""P6 — minimise to tray + toasts while hidden.

Two halves. The **pure** half is ``model.toast_for``: it must make the *same* pick as the sound
(``sound.advance_cue`` — one thing per advance, priority-ordered) and only add wording. The
**wiring** half drives a real ``TraderGUI`` in a subprocess (see test_gui_smoke.py for why),
with two substitutions the offscreen platform forces: ``_tray_usable`` is patched to True
(offscreen reports no system tray), and the ``QSystemTrayIcon`` is swapped for a recorder, so
``showMessage`` calls can be asserted instead of vanishing into a tray that isn't there.

What's worth defending: toasts fire only while hidden, at most one per advance; the margin-call
box never pops over a hidden window but does when it comes back; minimise goes to the tray only
when the option is on; turning the option off never strands a hidden window; and close still
quits.
"""
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace as N

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Pure — toast_for
# --------------------------------------------------------------------------- #

def _order(sym="ACME", side="buy", qty=2.0):
    return N(asset_id=f"STOCK:{sym}", side=N(value=side), quantity=qty)


def _fired(sym="ACME", filled=True, msg=None):
    return N(filled=filled, order=_order(sym), price=12.5,
             message=msg or ("stop filled" if filled else "stop cancelled: insufficient buying power"))


def _closure(sym="ACME"):
    return N(order=_order(sym), price=9.0, realized_pnl=-30.0)


def test_toast_is_quiet_when_the_sound_would_be():
    from trader_pro.gui.model import toast_for

    assert toast_for([], [], []) is None
    assert toast_for([N(kind="earnings", headline="x")], [], []) is None


def test_toast_makes_the_sounds_pick():
    """One judgement, two outputs: whatever advance_cue names, the toast talks about."""
    from trader_pro.gui.model import toast_for
    from trader_pro.sound import advance_cue

    swan = N(kind="flash_crash", headline="Exchange halts withdrawals")
    combos = [
        ([swan], [], []),
        ([], [_closure()], []),
        ([], [], [_fired()]),
        ([], [], [_fired(filled=False)]),
        ([swan], [_closure()], [_fired(), _fired(filled=False)]),
        ([], [_closure()], [_fired()]),
        ([], [], [_fired(filled=False), _fired()]),
    ]
    titles = {"black_swan": "⚠  Black swan", "margin_call": "⚠  Margin call",
              "order_fired": "Resting order filled", "cancel": "Resting order cancelled"}
    for events, closures, fills in combos:
        title, _ = toast_for(events, closures, fills)
        assert title == titles[advance_cue(events, closures, fills)], (events, closures, fills)


def test_toast_bodies_read_like_the_news_feed():
    from trader_pro.gui.model import pending_fill_entry, toast_for

    title, body = toast_for([], [], [_fired()])
    assert title == "Resting order filled"
    assert body == "stop filled — buy 2 ACME @ $12.50"
    assert body in pending_fill_entry(_fired())[0]            # what the feed will show

    title, body = toast_for([], [], [_fired(filled=False), _fired("BETA", filled=False)])
    assert title == "Resting order cancelled"
    assert body == "stop cancelled: insufficient buying power (ACME)  (+1 more)"

    title, body = toast_for([N(kind="flash_crash", headline="Exchange halts withdrawals")], [], [])
    assert (title, body) == ("⚠  Black swan", "Exchange halts withdrawals")

    title, body = toast_for([], [_closure("ZED"), _closure("ACME"), _closure("ACME")], [])
    assert title == "⚠  Margin call"
    assert body == "The broker force-closed 3 positions: ACME, ZED. Play is paused."
    _, body = toast_for([], [_closure()], [])
    assert body.startswith("The broker force-closed 1 position: ACME.")


# --------------------------------------------------------------------------- #
# Wiring — a real window, in a subprocess
# --------------------------------------------------------------------------- #

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not installed", allow_module_level=True)

_TRAY = textwrap.dedent(
    """
    import os, time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from trader_pro.cli import TraderApp
    import trader_pro.cli as cli
    from trader_pro.core import (World, load_seed_universe, OrderSide, OrderKind, place_pending,
                                 AssetKind, make_asset_id)
    from trader_pro.gui import app as A
    from trader_pro.gui.app import TraderGUI
    from trader_pro.settings import get_setting

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()

    class StubTray:
        def __init__(self): self.msgs = []; self.visible = False; self.tip = ""; self.icons = 0
        def showMessage(self, title, body, icon=None, ms=0): self.msgs.append((title, body, icon, ms))
        def show(self): self.visible = True
        def hide(self): self.visible = False
        def isVisible(self): return self.visible
        def setToolTip(self, t): self.tip = t
        def setIcon(self, icon): self.icons += 1

    boxes = []
    QMessageBox.warning = staticmethod(lambda *a, **k: boxes.append(a[1]))   # never block offscreen
    TraderGUI._tray_usable = lambda self: True                              # offscreen has no tray

    def fresh(seed=1):
        return TraderApp(World.new(uni, world_seed=seed, profile="Normal", starting_cash=100_000.0),
                         universe=uni)

    gui = TraderGUI(fresh())
    gui.autosave_enabled = False
    assert isinstance(gui._tray, QSystemTrayIcon)      # the real one is built at boot...
    assert not gui.tray_mode and not gui.act_tray.isChecked()
    assert not gui._tray.isVisible(), "tray icon shown while the option is off"
    tray = StubTray(); gui._tray = tray                # ...and swapped for the recorder here
    gui.show(); app.processEvents()
    print("boot ok")

    # --- the toggle: shows the icon, persists ------------------------------------------------
    gui.act_tray.setChecked(True)
    assert gui.tray_mode and get_setting("tray") is True and tray.visible
    gui.act_tray.setChecked(False)
    assert not gui.tray_mode and get_setting("tray") is False and not tray.visible
    print("toggle ok")

    # --- minimise: a plain minimise while off, the tray while on -----------------------------
    gui.showMinimized(); app.processEvents(); app.processEvents()
    assert not gui._in_tray and not gui.isHidden(), "minimised to the tray with the option off"
    gui.showNormal(); app.processEvents()
    gui.act_tray.setChecked(True)
    gui.showMinimized(); app.processEvents(); app.processEvents()
    assert gui._in_tray and gui.isHidden(), "the option is on, but minimise didn't go to the tray"
    assert not app.quitOnLastWindowClosed()
    assert "net worth" in tray.tip
    print("minimise ok")

    # --- toasts only while hidden, one per advance -------------------------------------------
    aid = make_asset_id(AssetKind.STOCK, uni.stocks[0].symbol)
    px = gui.trader.world.price(aid)
    place_pending(gui.trader.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)
    place_pending(gui.trader.world, aid, OrderSide.BUY, 1, OrderKind.LIMIT, px * 1.5)
    gui._advance_now(1)
    assert len(tray.msgs) == 1, tray.msgs
    assert tray.msgs[0][0] == "Resting order filled" and "(+1 more)" in tray.msgs[0][1]
    assert tray.msgs[0][2] == QSystemTrayIcon.MessageIcon.Information
    gui._advance_now(1)                                # quiet advance: no toast
    assert len(tray.msgs) == 1
    # ...and the live timer — the path that actually runs while you're away
    gui.playing = True; gui._play_clock = time.monotonic() - 5; gui._tick_accum = 0.0
    place_pending(gui.trader.world, aid, OrderSide.BUY, 1, OrderKind.LIMIT, px * 1.5)
    gui._on_timer()
    assert len(tray.msgs) == 2 and tray.msgs[-1][0] == "Resting order filled", tray.msgs
    gui.playing = False; gui._play_clock = None
    print("toast ok")

    # --- a margin call while hidden: toast + pause, the box waits ----------------------------
    gui.playing = False; gui.toggle_play(); assert gui.playing
    cli.liquidate_for_margin = lambda world: [type("C", (), {
        "order": type("O", (), {"asset_id": aid, "quantity": 1.0})(), "price": px, "realized_pnl": -1.0})()]
    gui._advance_now(1)
    cli.liquidate_for_margin = lambda world: []
    assert tray.msgs[-1][0] == "⚠  Margin call" and tray.msgs[-1][2] == QSystemTrayIcon.MessageIcon.Warning
    assert not gui.playing, "a margin call must still pause while hidden"
    assert boxes == [], "the margin-call box popped over a hidden window"
    assert gui._deferred_margin_call
    print("hidden margin call ok")

    # --- restore: window back, box now, no more toasts ---------------------------------------
    gui._restore_from_tray(); app.processEvents()
    assert not gui._in_tray and gui.isVisible() and not gui.isMinimized()
    assert app.quitOnLastWindowClosed()
    assert boxes == ["⚠  Margin Call"], boxes
    assert gui._deferred_margin_call is None
    n = len(tray.msgs)
    place_pending(gui.trader.world, aid, OrderSide.BUY, 1, OrderKind.LIMIT, px * 1.5)
    gui._advance_now(1)
    assert len(tray.msgs) == n, "toasted while the window was on screen"
    assert tray.visible, "option on: the icon stays"
    print("restore ok")

    # --- Ctrl+H works with the option off, and switching the option off restores -------------
    gui.act_tray.setChecked(False)
    gui.action_hide_to_tray(); app.processEvents()
    assert gui._in_tray and tray.visible
    gui._restore_from_tray(); app.processEvents()
    assert not tray.visible, "option off: the icon goes when the window is back"
    gui.act_tray.setChecked(True)
    gui.action_hide_to_tray(); app.processEvents()
    gui.act_tray.setChecked(False); app.processEvents()
    assert not gui._in_tray and gui.isVisible(), "turning the option off stranded a hidden window"
    print("hide/unstrand ok")

    # --- boot honours the persisted on; accent change repaints the icon ----------------------
    gui.act_tray.setChecked(True)
    gui2 = TraderGUI(fresh(2)); gui2.autosave_enabled = False
    assert gui2.tray_mode and gui2.act_tray.isChecked() and gui2._tray.isVisible()
    t2 = StubTray(); gui2._tray = t2
    gui2.set_accent("#3399ff")
    assert t2.icons == 1
    print("restore-on-boot ok")

    # --- quit from the tray: the close path runs (prefs saved), then the loop ends -----------
    gui2.act_tray.setChecked(False)
    quits = []
    app.quit = lambda: quits.append(1)
    gui2.action_quit()
    assert quits == [1] and get_setting("geometry"), "quit skipped close (no prefs written)"
    print("quit ok")
    print("TRAY OK")
    """
)


def test_tray_wiring_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", _TRAY],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "TRAY OK" in proc.stdout, detail
