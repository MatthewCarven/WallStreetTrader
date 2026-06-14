"""Event system tests (V1.4)."""

from __future__ import annotations

import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, AssetKind, make_asset_id, EventSchedule,
)
from trader_pro.core.profiles import get_profile  # noqa: E402
from trader_pro.core.engine import DAY  # noqa: E402

U = load_seed_universe()
SEED = 20260614


def _swan_count(profile: str, years: int = 1) -> int:
    sched = EventSchedule(SEED, U, get_profile(profile))
    return sum(1 for d in range(365 * years)
               for ev in sched._events_for_day(d) if ev.kind == "flash_crash")


def test_schedule_is_deterministic() -> None:
    a = EventSchedule(SEED, U, get_profile("Volatile"))
    b = EventSchedule(SEED, U, get_profile("Volatile"))
    ea = [(e.fire_tick, e.kind, e.severity) for e in a._events_for_day(30)]
    eb = [(e.fire_tick, e.kind, e.severity) for e in b._events_for_day(30)]
    assert ea == eb and len(ea) >= 0


def test_price_with_events_still_fast_forwards_exactly() -> None:
    a = MarketEngine(World.new(U, SEED, profile="Volatile")); a.advance(900)
    b = MarketEngine(World.new(U, SEED, profile="Volatile")); b.advance_to(900)
    for s in U.stocks[:30]:
        sid = make_asset_id(AssetKind.STOCK, s.symbol)
        assert abs(a.price_at(sid, 900) - b.price_at(sid, 900)) < 1e-7


def test_black_swans_scale_with_profile() -> None:
    assert _swan_count("Calm") < _swan_count("Normal") < _swan_count("Apocalyptic")


def test_a_black_swan_actually_crashes_the_market() -> None:
    sched = EventSchedule(SEED, U, get_profile("Apocalyptic"))
    swan = None
    for d in range(20, 365):
        for ev in sched._events_for_day(d):
            if ev.kind == "flash_crash" and ev.fire_tick > 25 * DAY:
                swan = ev; break
        if swan:
            break
    assert swan is not None
    eng = MarketEngine(World.new(U, SEED, profile="Apocalyptic"))
    sample = [make_asset_id(AssetKind.STOCK, s.symbol) for s in U.stocks[:40]]
    before = st.mean(eng.price_at(a, swan.fire_tick - 30) for a in sample)
    after = st.mean(eng.price_at(a, swan.fire_tick + 120) for a in sample)
    assert after < before * 0.95          # market-wide drop right after the swan


def test_news_and_fired_between() -> None:
    sched = EventSchedule(SEED, U, get_profile("Volatile"))
    t = 60 * DAY
    recent = sched.recent(t, lookback_days=20)
    assert all(e.fire_tick <= t for e in recent)
    window = sched.fired_between(10 * DAY, 11 * DAY)
    assert all(10 * DAY < e.fire_tick <= 11 * DAY for e in window)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all event tests passed")
