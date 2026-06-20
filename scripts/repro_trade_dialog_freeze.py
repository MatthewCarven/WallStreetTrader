#!/usr/bin/env python3
"""Minimal reproduction of the trade-dialog freeze (see docs/freeze-bug/README.md).

Two modes:

  python scripts/repro_trade_dialog_freeze.py          # headless, cross-platform (Windows ok)
  python scripts/repro_trade_dialog_freeze.py --pty     # drives the real terminal app (Unix/WSL)

Headless mode runs the TUI under Textual's `run_test` pilot in a subprocess and applies a
wall-clock timeout. The freeze deadlocks the event loop so completely that an in-process
asyncio timeout can't fire, hence the subprocess. It opens the trade dialog and dismisses it;
if the process doesn't finish, the freeze reproduced.

--pty mode launches `play_tui.py` in a real pseudo-terminal (needs `pexpect`, Unix/macOS/WSL),
buys in the dialog, then sends 'q': if the app won't quit, it's frozen.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20


# --------------------------------------------------------------------------- #
# Headless reproduction (cross-platform)
# --------------------------------------------------------------------------- #

def _scenario() -> None:
    import asyncio
    sys.path.insert(0, str(ROOT))
    from textual.widgets import DataTable
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
            await pilot.press("enter")          # open dialog
            await pilot.pause()
            await pilot.press("escape")         # dismiss -> deadlocks here on the buggy code
            await pilot.pause(); await pilot.pause()
        print("RESPONSIVE")

    asyncio.run(run())


def headless() -> int:
    try:
        proc = subprocess.run([sys.executable, __file__, "__scenario__"],
                              cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT)
        print("RESULT: RESPONSIVE (no freeze) ->", proc.stdout.strip() or "ok")
        return 0
    except subprocess.TimeoutExpired:
        print("RESULT: FROZEN (bug reproduced) -- dialog dismiss deadlocked Textual teardown")
        return 1


# --------------------------------------------------------------------------- #
# Real-terminal reproduction (Unix / WSL, needs pexpect)
# --------------------------------------------------------------------------- #

def pty() -> int:
    try:
        import pexpect
    except ImportError:
        print("--pty needs `pexpect` (pip install pexpect); not available on native Windows.")
        return 2
    env = {"TERM": "xterm-256color", "PYTHONUNBUFFERED": "1", "PATH": "/usr/bin:/bin"}
    child = pexpect.spawn(sys.executable, [str(ROOT / "play_tui.py")], cwd=str(ROOT),
                          env=env, dimensions=(38, 110), timeout=15)
    try:
        child.expect("Welcome to Trader PRO", timeout=12)
    except Exception:
        print("could not start the TUI"); return 2
    time.sleep(0.8)
    child.send(b"\r"); time.sleep(0.7)                       # open dialog on the first row
    child.send(b"$100"); time.sleep(0.3); child.send(b"\r")  # an affordable buy -> dialog closes
    time.sleep(1.0)
    child.send(b"q")                                         # ask the app to quit
    try:
        child.expect(pexpect.EOF, timeout=6)
        print("RESULT: RESPONSIVE (quit cleanly)"); return 0
    except pexpect.TIMEOUT:
        print("RESULT: FROZEN (bug reproduced) -- app ignored 'q' after the dialog closed")
        child.kill(9); return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "__scenario__":
        _scenario()
    elif len(sys.argv) > 1 and sys.argv[1] == "--pty":
        sys.exit(pty())
    else:
        sys.exit(headless())
