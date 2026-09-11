"""P5 L2 — the desktop GUI's sound wiring, driven in a subprocess (PySide6's shiboken import
hook and Textual's lazy modules must not share an interpreter — see test_gui_smoke.py).

Two scripts. The **wiring** one installs a recording player on a real ``TraderGUI`` and checks
the plumbing end to end: the Appearance ▸ Sound toggle, the preference it writes, a dialog fill
cueing by verb, a cancel from the orders dialog, a resting order firing through ``_advance``, and
the toggle actually gating playback. The **backend** one builds the real ``QtPlayer`` with the
mute flag *cleared* and waits for all six ``QSoundEffect`` objects to report ``Ready`` — the WAVs
decode in Qt — without ever calling ``play()``, so the suite stays silent, and with stderr
captured, so a QtMultimedia complaint can't hide behind a green result.
"""
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not installed", allow_module_level=True)


_WIRING = textwrap.dedent(
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp
    from trader_pro.core import (World, load_seed_universe, OrderSide, OrderKind, place_pending,
                                 AssetKind, make_asset_id)
    from trader_pro.gui.app import TraderGUI, OrdersDialog
    from trader_pro.settings import get_setting
    from trader_pro.sound import NullPlayer

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()

    class Recorder:
        def __init__(self): self.played = []
        def play(self, cue): self.played.append(cue)

    def fresh(seed=1):
        return TraderApp(World.new(uni, world_seed=seed, profile="Normal", starting_cash=100_000.0),
                         universe=uni)

    gui = TraderGUI(fresh())
    gui.autosave_enabled = False
    assert isinstance(gui._player, NullPlayer), "the suite's mute flag was ignored"
    assert gui.sound_on and gui.act_sound.isChecked(), "sound must default on"
    assert gui.trader.on_cue is not None, "the TraderApp never got a cue sink"
    rec = Recorder()
    gui._player = rec
    print("boot ok")

    # --- a dialog fill cues by verb -------------------------------------------------------
    aid = make_asset_id(AssetKind.STOCK, uni.stocks[0].symbol)
    sym = uni.stocks[0].symbol
    class R:  # the ExecutionResult shape _on_filled reads
        price = 10.0; fee = 0.0; realized_pnl = 0.0
    gui._on_filled("buy", 1, sym, R())
    gui._on_filled("short", 1, sym, R())
    gui._on_filled("cover", 1, sym, R())
    gui._on_filled("sell", 1, sym, R())
    assert rec.played == ["buy", "sell", "buy", "sell"], rec.played
    print("dialog fills ok")

    # --- the command line goes through TraderApp, which cues on its own ------------------
    gui.command_line.setText(f"buy {sym} 1")
    gui._run_command()
    assert rec.played[-1] == "buy", rec.played
    print("command line ok")

    # --- a resting order firing inside _advance_now --------------------------------------
    px = gui.trader.world.price(aid)
    place_pending(gui.trader.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)
    gui._advance_now(1)
    assert rec.played[-1] == "order_fired", rec.played
    gui._advance_now(1)                               # nothing resting: a quiet advance
    assert rec.played[-1] == "order_fired" and rec.played.count("order_fired") == 1
    print("advance ok")

    # --- a cancel from the orders dialog ---------------------------------------------------
    place_pending(gui.trader.world, aid, OrderSide.BUY, 1, OrderKind.LIMIT, px * 0.5)
    dlg = OrdersDialog(gui.trader, gui)
    dlg._cancel()
    assert rec.played[-1] == "cancel", rec.played
    assert gui.trader.world.portfolio.pending == []
    dlg._cancel()                                     # empty book: nothing to cancel, no tick
    assert rec.played.count("cancel") == 1
    print("cancel ok")

    # --- the toggle gates playback and persists ------------------------------------------
    n = len(rec.played)
    gui.act_sound.setChecked(False)                   # the menu path, not set_sound directly
    assert gui.sound_on is False
    assert get_setting("sound") is False, "toggle not persisted"
    gui._on_filled("buy", 1, sym, R())
    gui._advance_now(1)
    assert len(rec.played) == n, "muted, but something played"
    gui.act_sound.setChecked(True)
    assert get_setting("sound") is True
    gui._on_filled("buy", 1, sym, R())
    assert len(rec.played) == n + 1
    print("toggle ok")

    # --- boot honours the persisted off ----------------------------------------------------
    gui.act_sound.setChecked(False)
    gui2 = TraderGUI(fresh(2))
    gui2.autosave_enabled = False
    assert gui2.sound_on is False and not gui2.act_sound.isChecked()
    rec2 = Recorder(); gui2._player = rec2
    gui2._on_filled("buy", 1, sym, R())
    assert rec2.played == []
    print("restore ok")
    print("SOUND WIRING OK")
    """
)


_BACKEND = textwrap.dedent(
    """
    import os, sys, time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("TRADER_PRO_MUTE", None)           # the real thing, this once
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtMultimedia import QSoundEffect
    from trader_pro.gui.sound import gui_player, QtPlayer
    from trader_pro.sound import CUES

    app = QCoreApplication.instance() or QCoreApplication([])
    player = gui_player()
    assert isinstance(player, QtPlayer), type(player)
    assert set(player.loaded) == set(CUES), player.loaded
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        app.processEvents()
        states = {c: e.status() for c, e in player._effects.items()}
        if all(s == QSoundEffect.Status.Ready for s in states.values()):
            break
        assert not any(s == QSoundEffect.Status.Error for s in states.values()), states
    else:
        raise SystemExit(f"not all cues loaded in 10s: {states}")
    player.play("klaxon")                             # unknown cue: a no-op, never a raise
    print("SOUND BACKEND OK")
    """
)


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )


def test_sound_wiring_in_subprocess():
    proc = _run(_WIRING)
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "SOUND WIRING OK" in proc.stdout, detail


def test_qt_player_loads_every_cue_without_a_word_on_stderr():
    proc = _run(_BACKEND)
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "SOUND BACKEND OK" in proc.stdout, detail
    assert proc.stderr.strip() == "", detail      # QtMultimedia grumbles are bugs, not noise
