"""Offscreen tests for P1 session memory.

The GUI restores speed / chart range / board view / sort from ``settings.json`` at boot, persists
them (plus window geometry) at close, and treats the file as untrusted input — junk values keep
the defaults. Runs the Qt work in a subprocess for the same shiboken-vs-Textual reason as
``test_gui_smoke.py``. The autouse fixture in ``conftest.py`` points ``TRADER_PRO_SETTINGS_DIR``
at a per-test tmp dir which the child inherits, so parent and child share a *private* settings
file and never touch a developer's real one.
"""
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trader_pro.gui.settings as S            # noqa: E402  (Qt-free)

if importlib.util.find_spec("PySide6") is None:
    pytest.skip("PySide6 not installed", allow_module_level=True)

_BOOT = """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp
    from trader_pro.core import World, load_seed_universe
    from trader_pro.gui.app import TraderGUI
    import trader_pro.gui.settings as S

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    gui = TraderGUI(TraderApp(world, universe=uni))
    gui.autosave_enabled = False              # never write into saves/ during tests
"""

_RESTORE = textwrap.dedent(_BOOT + """
    from trader_pro.gui.model import CHART_RANGES, SPEEDS
    from trader_pro.core import AssetKind

    # conftest's env dir was pre-seeded by the parent: speed=2, chart_range=0, view=stocks, sort on
    assert gui.speed_idx == 2, gui.speed_idx
    assert gui.speed_label.text() == SPEEDS[2][0]
    assert gui.chart_range == 0, gui.chart_range
    assert gui.range_btn.text().endswith(CHART_RANGES[0][0])
    assert gui.view_label == "stocks", gui.view_label
    assert gui.view_btns["stocks"].isChecked()
    assert all(gui.trader.world.kind_of(a) is AssetKind.STOCK for a in gui.board_model.aids)
    assert gui.sort_by_change is True and gui.sort_btn.isChecked()
    assert gui.board_model.sort_active is True     # the restored sort actually reached the board
    assert gui.movers is False
    print("RESTORE OK")
""")

_RESTORE_MOVERS = textwrap.dedent(_BOOT + """
    # movers is the odd one out — it doesn't go through _set_view, so restore it explicitly
    assert gui.view_label == "movers" and gui.movers is True
    assert gui.view_btns["movers"].isChecked()
    assert gui.owned_only is False
    assert gui.board_model.rowCount() > 0
    print("MOVERS OK")
""")

_PERSIST = textwrap.dedent(_BOOT + """
    # start from the defaults (empty settings dir), change everything, then close the window —
    # closeEvent is the real persistence path (autosave itself is disabled above).
    assert gui.speed_idx == 0 and gui.chart_range == 1 and gui.view_label == "watchlist"
    gui.faster()                                  # speed 0 -> 1
    gui.cycle_chart_range()                       # range 1 -> 2
    gui.view_bonds()
    gui.toggle_sort()
    gui.close()

    data = S.load_settings()                      # env-resolved: the test's private file
    assert data.get("speed") == 1, data
    assert data.get("chart_range") == 2, data
    assert data.get("view") == "bonds", data
    assert data.get("sort_1d") is True, data
    geo = data.get("geometry")
    assert isinstance(geo, str) and geo and bytes.fromhex(geo), data   # a real hex geometry blob
    print("PERSIST OK")
""")

_JUNK = textwrap.dedent(_BOOT + """
    # parent seeded out-of-range / wrong-type values: every one must fall back to the default
    assert gui.speed_idx == 0, gui.speed_idx
    assert gui.chart_range == 1, gui.chart_range
    assert gui.view_label == "watchlist", gui.view_label
    assert gui.sort_by_change is False
    gui.trader._advance(60)                        # and the app still runs fine afterwards
    gui._refresh_header()
    print("JUNK OK")
""")


def _run(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "OK" in proc.stdout, detail


def test_session_restore_in_subprocess():
    S.update_settings({"speed": 2, "chart_range": 0, "view": "stocks", "sort_1d": True})
    _run(_RESTORE)


def test_movers_view_restores_in_subprocess():
    S.update_settings({"view": "movers"})
    _run(_RESTORE_MOVERS)


def test_session_persist_on_close_in_subprocess():
    _run(_PERSIST)


def test_junk_settings_keep_defaults_in_subprocess():
    S.update_settings({"speed": 99, "chart_range": -4, "view": "bogus",
                       "sort_1d": "yes", "geometry": "zz-not-hex"})
    _run(_JUNK)
