"""Does the trade-dialog freeze depend on the number of Buttons? (Spoiler: no.)

Matthew asked whether the dialog still freezes with no buttons / one / two. It does -- the
freeze is independent of the button count: 0, 1, 2, 3 and 4 buttons all hang on dismiss. These
parametrized tests document that across the whole range. (The actual trigger is a fragile race
in Textual's screen teardown, not the buttons -- see docs/freeze-bug/README.md.)

Each case runs the real TUI headlessly under `run_test`, with `TradeDialog.compose` patched to
render N buttons, dismisses the dialog (Esc) and checks the app still responds to input. The
deadlock blocks the event loop so hard that an in-loop timeout can't fire, so each case runs in
a subprocess with a wall-clock timeout. Cross-platform: no PTY / pexpect, runs on Windows.

Marked xfail (the bug is unfixed) with strict=False, so the body still runs: today every case
fails -> xfail; once the dialog is fixed they'll pass -> XPASS, which is the signal to delete
the xfail marker so these become hard regression guards.

Run standalone for a quick ALIVE/FROZEN grid:
    python tests/test_tui_dialog_button_count.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 12                       # a healthy dismiss finishes in well under a second
BUTTON_COUNTS = (0, 1, 2, 3, 4)


def _check(n_buttons: int, dismiss: str = "cancel") -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [sys.executable, __file__, "__scenario__", str(n_buttons), dismiss],
            cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT,
        )
        return ("RESPONSIVE" in proc.stdout), (proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired:
        return False, "timed out -> dialog dismiss deadlocked (freeze reproduced)"


def _textual_broken() -> bool:
    """True on Textual >= 0.72.0 — the versions with the teardown regression (docs/freeze-bug)."""
    try:
        from importlib.metadata import version
        parts = version("textual").split(".")
        return (int(parts[0]), int(parts[1])) >= (0, 72)
    except Exception:
        return False


try:
    import pytest

    @pytest.mark.xfail(_textual_broken(),
                       reason="Textual >=0.72 deadlocks the dialog teardown for every button "
                              "count (docs/freeze-bug); the game pins textual<0.72.", strict=True)
    @pytest.mark.parametrize("n_buttons", BUTTON_COUNTS)
    def test_dialog_dismiss_is_independent_of_button_count(n_buttons):
        try:
            import textual  # noqa: F401
        except ImportError:
            pytest.skip("textual not installed")
        ok, out = _check(n_buttons)
        assert ok, f"TUI froze on dismiss with {n_buttons} button(s)\n{out}"
except ImportError:
    pass


# --------------------------------------------------------------------------- #
# Subprocess entry point: drive the TUI with TradeDialog rendering N buttons.
# --------------------------------------------------------------------------- #

def _scenario(n_buttons: int, dismiss: str) -> None:
    import asyncio
    sys.path.insert(0, str(ROOT))
    from textual.app import ComposeResult
    from textual.containers import Vertical, Horizontal
    from textual.widgets import Static, Input, Button, DataTable
    import trader_pro.tui as tui  # noqa: F401  (ensures package import)
    from trader_pro.tui import TraderTUI, TradeDialog
    from trader_pro.cli import TraderApp
    from trader_pro.core import load_seed_universe, World

    ids = [("buy", "success"), ("sell", "error"), ("short", "warning"), ("cover", "primary")]

    def compose(self) -> ComposeResult:
        with Vertical(id="trade-box"):
            yield Static(id="trade-info")
            yield Input(placeholder="quantity:  10  /  $500  /  all", id="qty")
            if n_buttons > 0:
                with Horizontal(id="trade-buttons"):
                    for i in range(n_buttons):
                        bid, var = ids[i]
                        yield Button(bid.capitalize(), variant=var, id=bid)
            yield Static(id="trade-msg")
    TradeDialog.compose = compose          # keep the real on_mount / handlers / dismiss

    U = load_seed_universe()

    async def run() -> None:
        app = TraderTUI(TraderApp(
            World.new(U, 20260614, profile="Normal", starting_cash=200_000.0), universe=U))
        async with app.run_test() as pilot:
            board = app.query_one("#board", DataTable)
            board.focus(); board.move_cursor(row=0)
            await pilot.press("enter")                      # open the dialog
            await pilot.pause()
            assert len(app.screen_stack) == 2, "dialog did not open"
            if dismiss == "cancel":
                await pilot.press("escape")
            else:
                app.screen.query_one("#qty", Input).value = "$100"
                await pilot.pause()
                await pilot.press("enter")                  # buy -> dialog closes
            await pilot.pause(); await pilot.pause()
            assert len(app.screen_stack) == 1, "dialog did not close"
            await pilot.press("2")                          # still responsive?
            await pilot.pause()
            assert app.view_label == "stocks", "app stopped responding after dismiss"
        print("RESPONSIVE")

    asyncio.run(run())


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "__scenario__":
        _scenario(int(sys.argv[2]), sys.argv[3])
    else:
        print(f"{'buttons':>8}  {'cancel':>8}  {'buy':>8}")
        for n in BUTTON_COUNTS:
            c_ok, _ = _check(n, "cancel")
            b_ok, _ = _check(n, "buy")
            print(f"{n:>8}  {'ALIVE' if c_ok else 'FROZEN':>8}  {'ALIVE' if b_ok else 'FROZEN':>8}")
