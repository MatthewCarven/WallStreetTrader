#!/usr/bin/env python3
"""Visualize a black-swan crash cascade (V1.4):  python scripts/cascade_demo.py

Builds a market index (average of many stocks) and a crypto, finds a black swan, and plots
the plunge + aftershocks + slow recovery, with event markers and the news headlines.
Writes cascade_chart.png.
"""

from __future__ import annotations

import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from trader_pro.core import load_seed_universe, World, MarketEngine, AssetKind, make_asset_id  # noqa: E402
from trader_pro.core.engine import DAY  # noqa: E402

U = load_seed_universe()
SEED = 20260614
PROFILE = "Volatile"


def main() -> None:
    eng = MarketEngine(World.new(U, SEED, profile=PROFILE))
    sched = eng.events

    # Find a black swan a few weeks in.
    swan = None
    for d in range(15, 200):
        for ev in sched._events_for_day(d):
            if ev.kind == "flash_crash" and ev.fire_tick > 20 * DAY:
                swan = ev; break
        if swan:
            break
    assert swan, "no swan found"
    centre = swan.fire_tick
    t0, t1 = centre - 12 * DAY, centre + 45 * DAY

    sample = [make_asset_id(AssetKind.STOCK, s.symbol) for s in U.stocks[:60]]
    crypto = make_asset_id(AssetKind.CRYPTO, "SLR")
    bond = make_asset_id(AssetKind.BOND, "GOVT-30Y")

    xs = list(range(t0, t1, 30))
    days = [(x - centre) / DAY for x in xs]
    base_idx = st.mean(eng.price_at(a, t0) for a in sample)
    index = [st.mean(eng.price_at(a, x) for a in sample) / base_idx * 100 for x in xs]
    cry = [eng.price_at(crypto, x) for x in xs]
    bnd = [eng.price_at(bond, x) for x in xs]

    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    ax[0].plot(days, index, color="tab:blue", lw=1.1)
    ax[0].set_title("Market index (avg of 60 stocks, =100 at left)", fontsize=10, loc="left")
    ax[1].plot(days, cry, color="tab:orange", lw=1.0)
    ax[1].set_title("Solaris (crypto)", fontsize=10, loc="left")
    ax[2].plot(days, bnd, color="tab:green", lw=1.1)
    ax[2].set_title("Govt 30Y bond — flight to safety", fontsize=10, loc="left")
    ax[2].set_xlabel("days from the black swan")

    # Mark the swan + aftershocks.
    window = [e for e in sched.fired_between(t0, t1)]
    for a in ax:
        a.grid(alpha=0.25)
        a.axvline(0, color="red", lw=1.4, alpha=0.7)
        for e in window:
            if e.kind == "aftershock":
                a.axvline((e.fire_tick - centre) / DAY, color="red", lw=0.6, alpha=0.25)

    head = swan.headline
    n_after = sum(1 for e in window if e.kind == "aftershock")
    fig.suptitle(f"Trader PRO V1.4 — crash cascade ({PROFILE})\n"
                 f"“{head}”  +{n_after} aftershocks", fontsize=12)
    fig.tight_layout()
    out = ROOT / "cascade_chart.png"
    fig.savefig(out, dpi=110)
    print(f"swan: {head}  (tick {centre}, {n_after} aftershocks)")
    print(f"chart -> {out}")


if __name__ == "__main__":
    main()
