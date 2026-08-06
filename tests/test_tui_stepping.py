"""Manual stepping (s / h / d) coalesces held-key repeats into one advance + one redraw.

Each press used to run its own `_advance` plus a full `_refresh` (which clears and rebuilds the
whole board) — about 33 ms of work, so a key-repeat rate faster than that queued work the app
couldn't drain, and the backlog was still unwinding at quit. These tests pin the replacement:

* a single tap still advances **immediately** (leading edge — no added latency),
* repeats inside the window are banked and applied as one batch,
* the number of redraws is bounded by drains, not by keypresses,
* and a modal can't be redrawn under, nor can banked ticks be lost to one.

They also pin the property the whole optimisation rests on: prices are a pure function of
(world_seed, tick), so advancing N ticks in one call lands exactly where N single ticks would.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.tui import TraderTUI  # noqa: E402
from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import World, load_seed_universe  # noqa: E402
from trader_pro.core.engine import DAY, HOUR  # noqa: E402

U = load_seed_universe()


def _app() -> TraderTUI:
    app = TraderTUI(TraderApp(
        World.new(U, 20260614, profile="Normal", starting_cash=5_000.0), universe=U))
    app.autosave_enabled = False
    return app


def _count_refreshes(app):
    """Wrap `_refresh` with a counter; returns a callable giving the count so far."""
    calls = []
    original = app._refresh

    def counted(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    app._refresh = counted
    return lambda: len(calls)


# --------------------------------------------------------------------------- #
# the invariant the batching relies on
# --------------------------------------------------------------------------- #

def test_batched_advance_lands_where_single_steps_would() -> None:
    """60 one-tick advances and one 60-tick advance agree — prices are pure in (seed, tick)."""
    one_at_a_time = TraderApp(World.new(U, 20260614, profile="Volatile", starting_cash=5_000.0),
                              universe=U)
    all_at_once = TraderApp(World.new(U, 20260614, profile="Volatile", starting_cash=5_000.0),
                            universe=U)
    for _ in range(60):
        one_at_a_time._advance(1)
    all_at_once._advance(60)

    assert one_at_a_time.world.market.tick_index == all_at_once.world.market.tick_index
    for aid in list(one_at_a_time.world.asset_ids())[:40]:
        assert one_at_a_time.world.price_of(aid) == all_at_once.world.price_of(aid), aid


# --------------------------------------------------------------------------- #
# the coalescing itself, through the pilot
# --------------------------------------------------------------------------- #

async def _scenario() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        refreshes = _count_refreshes(app)
        start = app.trader.world.market.tick_index

        # --- a single tap is applied straight away (no added latency) ---
        app.action_step()
        assert app.trader.world.market.tick_index == start + 1
        assert app._pending_steps == 0
        assert refreshes() == 1

        # --- a burst inside the window is banked, not applied one at a time ---
        for _ in range(50):
            app.action_step()
        assert app._pending_steps == 50                      # all banked…
        assert app.trader.world.market.tick_index == start + 1   # …clock hasn't moved yet
        assert refreshes() == 1                              # …and nothing redrew

        # --- the drain applies the whole batch in one advance + one redraw ---
        await pilot.pause(0.2)                               # let the drain timer fire
        assert app._pending_steps == 0
        assert app.trader.world.market.tick_index == start + 51
        assert refreshes() == 2, "51 presses must not cost 51 redraws"

        # --- mixed s/h/d in one window batch together ---
        mark = app.trader.world.market.tick_index
        app.action_hour()                                    # leading edge: applied now
        app.action_day()                                     # banked
        app.action_step()                                    # banked
        assert app._pending_steps == DAY + 1
        await pilot.pause(0.2)
        assert app.trader.world.market.tick_index == mark + HOUR + DAY + 1
        assert app._pending_steps == 0

        # --- a modal must not be redrawn under, and must not swallow banked ticks ---
        mark = app.trader.world.market.tick_index
        app._pending_steps = 120                             # as if keys landed just before it opened
        await pilot.press("ctrl+o")                          # OrdersScreen
        await pilot.pause()
        assert len(app.screen_stack) == 2
        app._drain_steps()                                   # would explode if it redrew under a modal
        assert app._pending_steps == 120                     # still banked, nothing lost
        assert app.trader.world.market.tick_index == mark
        await pilot.press("escape")
        await pilot.pause()
        app._drain_steps()                                   # back on the base screen: now it lands
        assert app._pending_steps == 0
        assert app.trader.world.market.tick_index == mark + 120


def test_tui_step_coalescing() -> None:
    asyncio.run(_scenario())


if __name__ == "__main__":
    test_batched_advance_lands_where_single_steps_would()
    test_tui_step_coalescing()
    print("all stepping tests passed")
