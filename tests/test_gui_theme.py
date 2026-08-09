"""P2 — the accent picker applies live, without a restart.

The palette used to be three module-level constants resolved at import (`ACCENT`, `ACCENT_HI`,
`SELECTION`), and every stylesheet string in `app.py` interpolated them when its widget was
built. Rebinding the module attribute afterwards changed nothing — the values were already
inside the strings — so the picker could only save the colour and say "restart to apply".

They now live on a mutable `THEME` object that every f-string reads at *format* time, and
`TraderGUI.set_accent()` re-runs the styling passes. This test drives that end to end on an
already-built window, which is exactly the case the old design could not satisfy.

Same subprocess dance as test_gui_smoke.py — PySide6's shiboken import hook and Textual's lazy
modules must not share an interpreter.
"""
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not installed", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[1]

_THEME = textwrap.dedent(
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp
    from trader_pro.core import World, load_seed_universe
    from trader_pro.gui.app import TraderGUI, HelpDialog
    from trader_pro.gui import model as M

    BLUE = "#3b82f6"
    BLUE_HI, BLUE_SEL = M._scale_hex(BLUE, 1.2), M._scale_hex(BLUE, 0.6)
    GREEN_DEFAULT, GREEN_SEL = "#2fae4e", "#1c682f"

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    gui = TraderGUI(TraderApp(world, universe=uni))
    gui.autosave_enabled = False
    gui.trader._advance(300)                      # some history, so the header/positions have text
    gui._refresh_header()

    def surfaces():
        '''Every long-lived surface that bakes an accent colour into a string.'''
        return {
            "window":  gui.styleSheet(),
            "news":    gui.news.styleSheet(),
            "command": gui.command_line.styleSheet(),
            "chart":   gui.chart.styleSheet(),
            "equity":  gui.equity_chart.styleSheet(),
            "header":  gui.header_label.text(),
        }

    # --- the window starts on the default phosphor green -------------------------------------
    before = surfaces()
    assert GREEN_DEFAULT in before["window"], before["window"]
    assert GREEN_SEL in before["window"], "row-selection colour missing from the base stylesheet"
    for name, text in before.items():
        assert BLUE not in text and BLUE_HI not in text, name
    print("default green ok")

    # --- pick an accent on an ALREADY-BUILT window: everything repaints -----------------------
    gui.set_accent(BLUE)
    after = surfaces()
    for name in ("window", "news", "command", "chart", "equity"):
        assert BLUE in after[name] or BLUE_HI in after[name] or BLUE_SEL in after[name], \\
            f"{name} did not repaint: {after[name]!r}"
        assert GREEN_DEFAULT not in after[name], f"{name} kept the old accent: {after[name]!r}"
    assert BLUE_SEL in after["window"], "board row-selection did not follow the accent"
    assert BLUE_HI in after["header"], "the TRADER PRO banner did not follow the accent"
    assert after != before
    print("live repaint ok")

    # the pyqtgraph axis pens follow too (they are set from THEME.selection, not a stylesheet)
    for w in (gui.chart, gui.equity_chart):
        assert w.getAxis("left").pen().color().name() == BLUE_SEL
    print("axis pens ok")

    # --- P&L semantics are NOT themeable ------------------------------------------------------
    # profit stays green and loss stays red in every theme; only chrome follows the accent.
    assert M.GREEN == "#2fae4e" and M.GREEN_HI == "#38c172" and M.RED == "#e5484d"
    ctx_up = M.RowCtx("X", 10.0, 5.0, 5.0, 5.0, 1.0, 10.0, 5.0, 100.0)
    ctx_dn = M.RowCtx("Y", 10.0, -5.0, -5.0, -5.0, 1.0, 10.0, 20.0, -50.0)
    assert M.cell(ctx_up, "chg").color == M.GREEN and M.cell(ctx_dn, "chg").color == M.RED
    assert M.cell(ctx_up, "pnl").color == M.GREEN and M.cell(ctx_dn, "pnl").color == M.RED
    print("pnl semantics ok")

    # --- a dialog opened AFTER the change is born in the new accent ---------------------------
    dlg = HelpDialog(gui)
    assert BLUE in dlg.styleSheet() or BLUE_HI in dlg.styleSheet(), dlg.styleSheet()
    assert GREEN_DEFAULT not in dlg.styleSheet()
    dlg.deleteLater()
    print("dialog ok")

    # --- reset goes back to phosphor green, live -----------------------------------------------
    gui.set_accent(None)
    back = surfaces()
    assert GREEN_DEFAULT in back["window"] and GREEN_SEL in back["window"]
    for name, text in back.items():
        assert BLUE not in text and BLUE_SEL not in text, name
    assert back["window"] == before["window"]          # byte-identical to how it booted
    print("reset ok")

    print("THEME OK")
    """
)


def test_accent_applies_live_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", _THEME],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "THEME OK" in proc.stdout, detail


def test_theme_object_is_mutable_and_derives_shades():
    """Pure, no Qt: the object the whole slice rests on."""
    from trader_pro.gui.model import Theme, _scale_hex

    t = Theme()                                   # default phosphor green
    assert t.as_tuple() == ("#2fae4e", "#38c172", "#1c682f")

    t.set("#3b82f6")
    assert t.accent == "#3b82f6"
    assert t.accent_hi == _scale_hex("#3b82f6", 1.2)
    assert t.selection == _scale_hex("#3b82f6", 0.6)

    t.set(None)                                   # back to the hand-tuned defaults
    assert t.as_tuple() == ("#2fae4e", "#38c172", "#1c682f")


def test_no_stale_palette_constants_remain():
    """The bug was a *copy* of the palette taken at import. Guard against one coming back:
    a module-level ACCENT / ACCENT_HI / SELECTION would be exactly that copy again."""
    from trader_pro.gui import model

    for name in ("ACCENT", "ACCENT_HI", "SELECTION"):
        assert not hasattr(model, name), (
            f"gui.model.{name} is back — read THEME.{name.lower()} at format time instead, "
            "or the accent picker silently stops applying live")
