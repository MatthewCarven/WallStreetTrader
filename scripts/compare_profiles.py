#!/usr/bin/env python3
"""Visualize all 8 market personalities on the same seed & asset.

    python scripts/compare_profiles.py  ->  profiles_chart.png

Each panel shows the SAME stock over the SAME 120 days under a different profile, so the
escalation from Calm to Apocalyptic is obvious at a glance. Also prints a parameter table.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from trader_pro.core import load_seed_universe, World, MarketEngine, AssetKind, make_asset_id  # noqa: E402
from trader_pro.core.profiles import PROFILES  # noqa: E402
from trader_pro.core.engine import DAY  # noqa: E402

U = load_seed_universe()
SEED = 20260614


def table() -> None:
    print(f"{'profile':<12}{'vol':>6}{'sent':>6}{'rate':>6}{'event':>7}{'casc':>6}{'predict':>9}")
    for p in PROFILES:
        print(f"{p.name:<12}{p.vol_mult:>6}{p.sentiment_mult:>6}{p.rate_mult:>6}"
              f"{p.event_rate_mult:>7}{p.cascade_mult:>6}{p.predictability:>9.2f}")


def chart() -> None:
    sym = U.stocks[10].symbol
    sid = make_asset_id(AssetKind.STOCK, sym)
    minutes = list(range(0, 120 * DAY, 60))   # 120 days, hourly samples
    days = [m / DAY for m in minutes]

    fig, axes = plt.subplots(4, 2, figsize=(12, 12), sharex=True)
    for ax, p in zip(axes.flat, PROFILES):
        eng = MarketEngine(World.new(U, SEED, profile=p.name))
        ax.plot(days, [eng.price_at(sid, m) for m in minutes], lw=0.7)
        ax.set_title(f"[{p.level}] {p.name}  (vol×{p.vol_mult})", fontsize=10, loc="left")
        ax.grid(alpha=0.25)
    for ax in axes[-1]:
        ax.set_xlabel("days")
    fig.suptitle(f"Trader PRO — same stock ({U.stocks[10].name}), same seed, 8 personalities",
                 fontsize=12)
    fig.tight_layout()
    out = ROOT / "profiles_chart.png"
    fig.savefig(out, dpi=110)
    print(f"\nchart -> {out}")


if __name__ == "__main__":
    table()
    chart()
