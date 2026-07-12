"""Offscreen smoke test for the GUI shell (Slice 0).

Runs the Qt work in a SUBPROCESS on purpose. Importing PySide6 (shiboken) installs a global
import hook that, on Python 3.14, collides with Textual's lazy-module machinery when both are
imported into a single interpreter (shiboken introspects each new import via `inspect`, and
`textual.widgets.__getattr__` raises ImportError on the `__wrapped__` probe). The GUI and the
Textual TUI never share a process in real use, so we keep PySide6 out of the main pytest
interpreter and exercise the window headlessly in a child process instead. Skipped if PySide6
isn't installed. The pure logic lives in test_gui_model.py (no Qt needed).
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

_SMOKE = textwrap.dedent(
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp, fmt_clock
    from trader_pro.core import World, load_seed_universe
    from trader_pro.gui.app import TraderGUI
    from trader_pro.gui.model import BOARD_COLUMNS

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    gui = TraderGUI(TraderApp(world, universe=uni))
    gui.autosave_enabled = False              # don't write into saves/ during tests

    # header builds and shows the live clock
    text = gui.header_label.text()
    assert "TRADER PRO" in text, text
    assert fmt_clock(gui.trader.world.market.tick_index) in text, text

    # advancing the market updates the header
    before = gui.header_label.text()
    gui.trader._advance(60)                    # +1 sim-hour
    gui._refresh_header()
    after = gui.header_label.text()
    assert before != after
    assert fmt_clock(gui.trader.world.market.tick_index) in after

    # play/pause toggles cleanly
    assert gui.playing is False
    gui.toggle_play()
    assert gui.playing is True and "playing" in gui.state_label.text()
    gui.toggle_play()
    assert gui.playing is False

    # --- Slice 1: time & speed controls ---
    from trader_pro.core.engine import DAY, HOUR
    from trader_pro.gui.model import SPEEDS

    assert gui.speed_idx == 0
    gui.faster()
    assert gui.speed_idx == 1 and "10 min/s" in gui.speed_label.text()
    gui.slower(); gui.slower()
    assert gui.speed_idx == 0                              # clamps at the slow end
    for _ in range(len(SPEEDS) + 3):
        gui.faster()
    assert gui.speed_idx == len(SPEEDS) - 1                # clamps at the fast end

    # discrete steps advance the clock exactly, regardless of play state
    t = gui.trader.world.market.tick_index
    gui.step_minute(); assert gui.trader.world.market.tick_index == t + 1
    gui.step_hour();   assert gui.trader.world.market.tick_index == t + 1 + HOUR
    gui.step_day();    assert gui.trader.world.market.tick_index == t + 1 + HOUR + DAY

    # keyboard shortcuts are wired onto the control buttons
    assert not gui.step_btn.shortcut().isEmpty()
    assert not gui.hour_btn.shortcut().isEmpty()
    assert not gui.day_btn.shortcut().isEmpty()
    assert not gui.faster_btn.shortcut().isEmpty()
    assert not gui.slower_btn.shortcut().isEmpty()

    # --- Slice 2: market board ---
    assert gui.board_model.rowCount() > 0
    assert gui.board_model.columnCount() == len(BOARD_COLUMNS)
    assert gui.board_model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "Symbol"
    price_cell = gui.board_model.data(gui.board_model.index(0, 1), Qt.DisplayRole)
    assert price_cell.startswith("$")                     # price column renders as money
    first_aid = gui.board_model.aid_at(0)
    assert first_aid and ":" in first_aid
    gui._refresh_board()                                  # live repaint keeps the model consistent
    assert gui.board_model.rowCount() > 0

    # --- Slice 3: board interaction (views / sort / paging / selection) ---
    from trader_pro.core import AssetKind
    gui.view_crypto()
    assert gui.board_model.rowCount() > 0
    assert all(gui.trader.world.kind_of(a) is AssetKind.CRYPTO for a in gui.board_model.aids)
    gui.view_stocks()
    assert all(gui.trader.world.kind_of(a) is AssetKind.STOCK for a in gui.board_model.aids)
    assert gui.board_model.rowCount() == 25               # one page of stocks
    page0 = list(gui.board_model.aids)
    gui.next_page()
    assert gui.view_page == 1 and list(gui.board_model.aids) != page0
    gui.view_owned()
    assert gui.board_model.rowCount() == 0                # nothing held on a fresh world
    gui.view_watch()
    assert gui.board_model.rowCount() > 0
    # row selection drives cursor_aid + the highlighted-asset label
    gui.board.selectRow(0)
    assert gui.cursor_aid == gui.board_model.aid_at(0) and ":" in gui.cursor_aid
    assert gui.selected_label.text().startswith("▶")
    # sort toggles cleanly
    gui.toggle_sort(); assert gui.sort_by_change is True
    gui.toggle_sort(); assert gui.sort_by_change is False

    # --- Slice 4: price chart ---
    from trader_pro.gui.model import CHART_RANGES
    gui.view_watch()
    gui.board.selectRow(0)
    gui._refresh_chart()
    xdata, ydata = gui._curve.getData()
    assert xdata is not None and len(xdata) > 1            # a real series for the selected asset
    r0 = gui.chart_range
    gui.cycle_chart_range()
    assert gui.chart_range == (r0 + 1) % len(CHART_RANGES)
    assert gui.range_btn.text().startswith("Range:")
    gui._refresh_chart()                                   # re-render at the new range, no crash

    # --- Slice 5: equity curve + asset detail ---
    gui.trader._advance(2 * 1440)                          # add net-worth history points
    gui._refresh_equity()
    ex, ey = gui._equity_curve.getData()
    assert ex is not None and len(ex) >= 1                 # equity curve has points
    gui.view_watch(); gui.board.selectRow(0)
    gui._refresh_detail()
    assert gui.cursor_aid.split(":", 1)[1] in gui.detail_label.text()   # detail shows the symbol

    # --- Slice 6: trade dialog (buy / sell / short / cover over execute_order) ---
    from trader_pro.gui.app import TradeDialog
    gui.view_watch(); gui.board.selectRow(0)
    aid = gui.cursor_aid
    cash0 = gui.trader.world.portfolio.cash
    dlg = TradeDialog(gui.trader, aid)
    dlg.qty.setText("$1000")
    dlg._act("buy")
    assert dlg.fill is not None and dlg.fill[0] == "buy"               # filled
    pos = gui.trader.world.portfolio.positions.get(aid)
    assert pos is not None and pos.quantity > 0                        # now holding it
    assert gui.trader.world.portfolio.cash < cash0                     # cash spent
    gui._on_filled(*dlg.fill)                                          # refresh path doesn't crash
    gui.view_owned()
    assert gui.board_model.rowCount() >= 1                             # holding shows in Owned
    # rejection: an absurd order shows a message and does not fill
    dlg2 = TradeDialog(gui.trader, aid)
    dlg2.qty.setText("999999999")
    dlg2._act("buy")
    assert dlg2.fill is None and dlg2.msg.text()
    # sell all closes the position
    dlg3 = TradeDialog(gui.trader, aid)
    dlg3.qty.setText("all")
    dlg3._act("sell")
    assert dlg3.fill is not None
    left = gui.trader.world.portfolio.positions.get(aid)
    assert left is None or abs(left.quantity) < 1e-9

    # --- Slice 7 (half): margin-risk meter ---
    from trader_pro.gui.model import margin_fill
    assert gui.margin_meter is not None
    gui._refresh_header()                                  # sync meter to current (flat) state
    assert gui.margin_meter._fill == 0.0                   # nothing held => empty
    dlgm = TradeDialog(gui.trader, aid); dlgm.qty.setText(""); dlgm._act("short")  # max short (2:1)
    assert dlgm.fill is not None
    gui._on_filled(*dlgm.fill)
    assert margin_fill(gui.trader.world) > 0.0             # leverage (the short) lifts the meter
    assert 0.0 <= gui.margin_meter._fill <= 1.0

    # --- Slice 7 (second half): positions table ---
    gui._refresh_positions()
    assert gui.positions_model.rowCount() >= 1             # the open position shows
    assert "Positions" in gui.pos_summary.text()

    # --- Slice 8: news feed, ticker, movers ---
    from trader_pro.core import MarketEvent
    assert gui.news.count() >= 1                           # welcome line at least
    gui._log_news([MarketEvent(1, "earnings", "asset", "STOCK:AAPL", 0.05, 1440.0, "AAPL pops")], [])
    assert gui.news.item(0).text().endswith("AAPL pops")   # newest on top
    gui._build_ticker(); gui._scroll_ticker()
    assert len(gui.ticker.text()) > 0                      # ticker has content
    gui.view_movers()
    assert gui.movers is True and gui.board_model.rowCount() > 0
    gui.view_watch()
    assert gui.movers is False

    # --- Slice 9: save / load / new world ---
    import tempfile
    from trader_pro.core import World as _World
    from trader_pro.gui.app import LoadDialog, NewWorldDialog
    from trader_pro.persistence import save_game as _sg, slot_path as _sp
    # new-world swap: fresh world (tick 0), view reset to watchlist, news cleared + seeded
    gui.trader.start_world(_World.new(gui.trader.universe, world_seed=777, profile="Calm",
                                      starting_cash=8000.0))
    gui._after_world_swap("New world 777")
    assert gui.trader.world.config.world_seed == 777 and gui.trader.world.market.tick_index == 0
    assert gui.movers is False and gui.view_label == "watchlist" and gui.news.count() >= 1
    # NewWorldDialog builds a (seed, profile, cash, fee) config
    nd = NewWorldDialog(); nd.seed.setText("123"); nd.cash.setText("2500"); nd._accept()
    assert nd.config[0] == 123 and nd.config[2] == 2500.0
    # LoadDialog lists a saved slot
    tmp = tempfile.mkdtemp()
    _sg(gui.trader.world, _sp("smoke_slot", tmp), label="smoke_slot")
    ld = LoadDialog(tmp)
    assert "smoke_slot" in [ld.list.item(i).data(Qt.UserRole) for i in range(ld.list.count())]

    # --- Slice 10: predictions, fees, command line ---
    from trader_pro.gui.app import HelpDialog, PredictDialog
    gui.view_crypto(); gui.board.selectRow(0)
    paid = gui.cursor_aid
    cash0 = gui.trader.world.portfolio.cash
    pd = PredictDialog(gui.trader, paid); pd._buy()
    assert pd.bought and "FORECAST" in pd.bought
    assert gui.trader.world.portfolio.cash < cash0             # forecast cost deducted
    # fees menu action sets the world's fee level
    gui.set_fee("high")
    assert gui.trader.world.config.fee_level == "high"
    # command line runs any CLI command (loan) and repaints
    gui.command_line.setText("loan 1000"); gui._run_command()
    assert gui.trader.world.portfolio.loan_balance() > 0
    assert gui.command_line.text() == ""                       # cleared after run
    # help dialog builds
    assert HelpDialog().windowTitle().startswith("Trader")

    print("SMOKE OK")
    """
)


def test_gui_shell_smoke_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", _SMOKE],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "SMOKE OK" in proc.stdout, detail
