"""Offscreen GUI test for resting stop/limit orders (Slice L5).

Like test_gui_smoke, the Qt work runs in a SUBPROCESS (PySide6's shiboken import hook collides
with Textual's lazy modules in one interpreter). Skipped if PySide6 isn't installed."""
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
    from PySide6.QtWidgets import QApplication
    from trader_pro.cli import TraderApp
    from trader_pro.core import World, load_seed_universe, OrderSide, OrderKind
    from trader_pro.gui.app import TraderGUI, TradeDialog, OrdersDialog

    app = QApplication.instance() or QApplication([])
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=100_000.0)
    gui = TraderGUI(TraderApp(world, universe=uni))
    gui.autosave_enabled = False

    gui.view_watch(); gui.board.selectRow(0)
    aid = gui.cursor_aid
    price = gui.trader.world.price(aid)

    # trade dialog with a trigger rests a stop/limit; buy BELOW price => LIMIT
    dlg = TradeDialog(gui.trader, aid)
    dlg.qty.setText("5"); dlg.trigger.setText(f"{price * 0.9:.4f}")
    dlg._act("buy")
    assert dlg.fill is not None and dlg.fill[0] == "resting", dlg.fill
    o = dlg.fill[1]
    assert o.side is OrderSide.BUY and o.kind is OrderKind.LIMIT and o.quantity == 5, o
    assert gui.trader.world.portfolio.pending[-1].id == o.id
    gui._on_rested(o)
    assert gui.news.item(0).text().startswith("rested"), gui.news.item(0).text()

    # ambient count shows in the positions summary
    gui._refresh_positions()
    assert "resting order" in gui.pos_summary.text(), gui.pos_summary.text()

    # buy ABOVE price => STOP (type inferred from the geometry)
    d2 = TradeDialog(gui.trader, aid)
    d2.qty.setText("2"); d2.trigger.setText(f"{price * 1.1:.4f}")
    d2._act("buy")
    assert d2.fill[1].kind is OrderKind.STOP, d2.fill

    # $amount converts at the trigger price; 'all' is refused for resting orders
    d3 = TradeDialog(gui.trader, aid)
    d3.qty.setText("$1000"); d3.trigger.setText("100")
    d3._act("sell")
    assert abs(d3.fill[1].quantity - 10.0) < 1e-9, d3.fill      # 1000 / 100
    d4 = TradeDialog(gui.trader, aid)
    d4.qty.setText("all"); d4.trigger.setText("100")
    d4._act("buy")
    assert d4.fill is None and d4.msg.text(), "resting 'all' should be rejected, dialog stays open"

    # a blank trigger is still a plain market order (regression)
    d5 = TradeDialog(gui.trader, aid)
    d5.qty.setText("1"); d5._act("buy")
    assert d5.fill is not None and d5.fill[0] == "buy", d5.fill

    # OrdersDialog lists the resting book and cancels the selected order
    n = len(gui.trader.world.portfolio.pending)
    assert n == 3, n                                            # LIMIT buy, STOP buy, sell $1000
    od = OrdersDialog(gui.trader)
    assert od.list.count() == n
    od.list.setCurrentRow(0); od._cancel()
    assert len(gui.trader.world.portfolio.pending) == n - 1
    assert od.list.count() == n - 1

    print("ORDERS OK")
    """
)


def test_gui_orders_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", _SMOKE],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
    )
    detail = f"\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    assert proc.returncode == 0, detail
    assert "ORDERS OK" in proc.stdout, detail
