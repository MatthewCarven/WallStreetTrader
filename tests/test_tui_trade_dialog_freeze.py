"""Regression test for the trade-dialog freeze bug (see docs/freeze-bug/README.md).

Opening the per-asset trade dialog (Enter on a row) and then dismissing it -- by buying or by
pressing Esc -- deadlocks Textual's screen teardown: `App.pop_screen`'s `do_pop` waits forever
on the dismissed dialog's child message-pump tasks, the event loop goes idle and stops
dispatching input, and the whole TUI freezes (Ctrl-C included, because the terminal is in raw
mode and Ctrl-C arrives as an unread keystroke rather than a signal).

The deadlock blocks the event loop so hard that an in-loop `asyncio.wait_for` can't even fire,
so we run the scenario in a *subprocess* and use a wall-clock timeout. That keeps this test
cross-platform (no PTY / pexpect) -- it runs on Windows, macOS and Linux.

Currently XFAIL: the bug is unfixed. When the dialog is fixed this test will XPASS; at that
point delete the `pytest.xfail(...)` line so it guards against regressions.

Run standalone (no pytest needed):
    python tests/test_tui_trade_dialog_freeze.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 25            # seconds; a healthy dismiss completes in well under a second


def _run_scenario_in_subprocess() -> tuple[bool, str]:
    """Returns (completed, output). completed=False means it hung (freeze reproduced)."""
    try:
        proc = subprocess.run(
            [sys.executable, __file__, "__scenario__"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT,
        )
        return True, (proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired:
        return False, "subprocess timed out -> dialog dismiss deadlocked (freeze reproduced)"


def _textual_broken() -> bool:
    """True on Textual >= 0.72.0 — the versions with the teardown regression (docs/freeze-bug).

    The game pins `textual<0.72`, so normally this is False and the test is a real guard. It only
    flips to xfail if someone installs a broken version.
    """
    try:
        from importlib.metadata import version
        parts = version("textual").split(".")
        return (int(parts[0]), int(parts[1])) >= (0, 72)
    except Exception:
        return False


try:
    import pytest

    @pytest.mark.xfail(_textual_broken(),
                       reason="Textual >=0.72 deadlocks the dialog teardown (docs/freeze-bug); "
                              "the game pins textual<0.72. An XPASS here means upstream fixed it "
                              "-> lift the cap in requirements.txt.", strict=True)
    def test_trade_dialog_dismiss_does_not_freeze():
        try:
            import textual  # noqa: F401
        except ImportError:                   # the TUI is an optional extra
            pytest.skip("textual not installed")
        completed, output = _run_scenario_in_subprocess()
        assert completed, f"TUI froze on trade-dialog dismiss.\n{output}"
except ImportError:
    pass


# --------------------------------------------------------------------------- #
# Subprocess entry point: drive the TUI headlessly and dismiss the dialog.
# --------------------------------------------------------------------------- #

def _scenario() -> None:
    import asyncio
    sys.path.insert(0, str(ROOT))
    from textual.widgets import DataTable, Input
    from trader_pro.tui import TraderTUI
    from trader_pro.cli import TraderApp
    from trader_pro.core import load_seed_universe, World

    U = load_seed_universe()

    async def run() -> None:
        app = TraderTUI(TraderApp(
            World.new(U, 20260614, profile="Normal", starting_cash=200_000.0), universe=U))
        async with app.run_test() as pilot:
            board = app.query_one("#board", DataTable)
            board.focus(); board.move_cursor(row=0)
            await pilot.press("enter")              # open the trade dialog
            await pilot.pause()
            assert len(app.screen_stack) == 2, "dialog did not open"
            # Drive a real BUY: this is the path that froze on Textual >=0.72 and, separately,
            # crashed with NoMatches('#log') on 0.71.x when the dialog logged from inside itself.
            app.screen.query_one("#qty", Input).value = "$100"
            await pilot.pause()
            await pilot.press("enter")              # submit buy -> dismiss + app logs/refreshes
            await pilot.pause()
            await pilot.pause()
            assert len(app.screen_stack) == 1, "dialog did not close"
            assert "CRYPTO:BTR" in app.trader.world.portfolio.positions, "buy did not fill"
            # prove input still flows after the dismiss:
            await pilot.press("2")                  # switch board view to stocks
            await pilot.pause()
            assert app.view_label == "stocks", "app stopped responding to keys after dismiss"
        print("RESPONSIVE")

    asyncio.run(run())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "__scenario__":
        _scenario()
    else:
        ok, out = _run_scenario_in_subprocess()
        print("RESULT:", "RESPONSIVE (no freeze)" if ok else "FROZEN (bug reproduced)")
        print(out)
        sys.exit(0 if ok else 1)
