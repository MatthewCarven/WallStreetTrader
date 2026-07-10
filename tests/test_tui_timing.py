"""Deterministic tests for live-play pacing (Space to play).

The market advances by REAL elapsed time * the current speed's ticks/second, so play runs at a
steady wall-clock pace (default 1 sim-minute per real second). To test that without sleeping, we
rebind ONLY the tui module's `time` name to a shim whose monotonic() we control -- Textual and
asyncio keep their own real `time`, so their scheduling is unaffected.
"""

from __future__ import annotations

import asyncio
import sys
import time as _real_time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trader_pro.tui as tui  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402

U = load_seed_universe()


class _TimeShim:
    def __init__(self, real):
        self._real = real
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def __getattr__(self, name):
        return getattr(self._real, name)


def _app() -> tui.TraderTUI:
    return tui.TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=100_000.0), universe=U))


async def _scenario() -> None:
    app = _app()
    shim = _TimeShim(_real_time)
    tui.time = shim
    ti = lambda: app.trader.world.market.tick_index
    try:
        async with app.run_test() as pilot:
            await pilot.pause()

            # default speed is the calm 1 sim-minute per real second
            assert app.speed_idx == 0
            assert tui.SPEEDS[0] == ("1 min/s", 1)

            # 1 min/s: no advance until a full real second has elapsed, then +1 tick
            app.playing = True
            app._play_clock = None
            app._tick_accum = 0.0
            shim.t = 1000.0
            app._on_timer()                       # baseline, no advance
            start = ti()
            for dt in (0.3, 0.6, 0.9):
                shim.t = 1000.0 + dt
                app._on_timer()
            assert ti() == start, "must not advance before one real second"
            shim.t = 1001.0
            app._on_timer()
            assert ti() == start + 1, "one sim-minute after one real second"

            # a faster tier scales proportionally: 10 min/s -> 10 ticks in one real second
            app.speed_idx = 1
            assert tui.SPEEDS[1] == ("10 min/s", 10)
            app._play_clock = None
            app._tick_accum = 0.0
            shim.t = 2000.0
            app._on_timer()
            b2 = ti()
            shim.t = 2001.0
            app._on_timer()
            assert ti() == b2 + 10

            # stall cap: a long freeze (sleep/GC) advances at most one real second's worth
            app.speed_idx = 0
            app._play_clock = None
            app._tick_accum = 0.0
            shim.t = 3000.0
            app._on_timer()
            b3 = ti()
            shim.t = 3030.0                       # 30s jump
            app._on_timer()
            assert ti() == b3 + 1, "stall must not fast-forward the market"

            # pause clears the baseline; resuming after a long gap does not jump
            app.playing = False
            shim.t = 3100.0
            app._on_timer()
            assert app._play_clock is None
            app.playing = True
            b4 = ti()
            shim.t = 3200.0                       # 100s paused gap
            app._on_timer()
            assert ti() == b4, "resume must set a fresh baseline, not bank paused time"

            # the `s` key steps exactly one sim-minute (one tick), not a "second"
            app.playing = False
            b5 = ti()
            await pilot.press("s")
            assert ti() == b5 + 1
    finally:
        tui.time = _real_time


def test_live_play_pacing() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_live_play_pacing()
    print("ok  test_live_play_pacing")
