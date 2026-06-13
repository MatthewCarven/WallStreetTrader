"""Market-profile tests (V0.5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    PROFILES as PROFILE_NAMES, get_profile, prediction_accuracy,
)
from trader_pro.core.profiles import PROFILES, DEFAULT_PROFILE  # noqa: E402


def test_eight_levels_in_canonical_order() -> None:
    assert PROFILE_NAMES == (
        "Calm", "Steady", "Normal-", "Normal",
        "Changing", "Unstable", "Volatile", "Apocalyptic",
    )
    assert [p.level for p in PROFILES] == list(range(1, 9))


def test_normal_is_the_unit_baseline() -> None:
    n = get_profile("Normal")
    assert n.vol_mult == n.sentiment_mult == n.rate_mult == 1.0
    assert n.event_rate_mult == n.cascade_mult == 1.0
    assert DEFAULT_PROFILE == "Normal"


def test_chaos_knobs_increase_monotonically() -> None:
    for field in ("vol_mult", "sentiment_mult", "rate_mult", "event_rate_mult", "cascade_mult"):
        vals = [getattr(p, field) for p in PROFILES]
        assert vals == sorted(vals), f"{field} not monotonically increasing"
        assert vals[0] < vals[-1]


def test_predictability_decreases_with_chaos() -> None:
    vals = [p.predictability for p in PROFILES]
    assert vals == sorted(vals, reverse=True)        # calmer = more foreseeable
    assert all(0.0 < v <= 1.0 for v in vals)
    assert prediction_accuracy("Calm") > prediction_accuracy("Apocalyptic")


def test_unknown_profile_raises() -> None:
    try:
        get_profile("Bananas")
    except ValueError as e:
        assert "Bananas" in str(e)
    else:
        raise AssertionError("expected ValueError for unknown profile")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all profile tests passed")
