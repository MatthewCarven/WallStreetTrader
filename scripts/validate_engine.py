#!/usr/bin/env python3
"""Validate & visualize the V0.3 engine.

    python scripts/validate_engine.py

Prints summary statistics and writes `validation_chart.png` — a quick eyeball of price
paths (stock, crypto, bond), the global mood, and the interest rate over ~90 days.
"""

from __future__ import annotations

import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, MarketEngine, AssetKind, make_asset_id,
)
from trader_pro.core.engine import DAY, HOUR, WEEK, sentiment_at, interest_rate_at  # noqa: E402

U = load_seed_universe()
SEED = 20260614


def stats() -> None:
    e = MarketEngine(World.new(U, SEED, profile="Normal"))
    sample = U.stocks[:80]

    def horizon(step, n):
        vals = []
        for s in sample:
            sid = make_asset_id(AssetKind.STOCK, s.symbol)
            px = [e.price_at(sid, k * step) for k in range(n)]
            r = [math.log(px[i] / px[i - 1]) for i in range(1, len(px)) if px[i - 1] > 0]
            vals.append(st.pstdev(r))
        return st.median(vals) * 100

    print("Return std (Normal profile):")
    print(f"  hourly  {horizon(HOUR, 200):5.2f}%")
    print(f"  daily   {horizon(DAY, 150):5.2f}%")
    print(f"  weekly  {horizon(WEEK, 80):5.2f}%")

    print("\nDaily std by profile:")
    a = make_asset_id(AssetKind.STOCK, sample[0].symbol)
    for p in ("Calm", "Steady", "Normal-", "Normal", "Changing", "Unstable", "Volatile", "Apocalyptic"):
        ep = MarketEngine(World.new(U, SEED, profile=p))
        r = [math.log(ep.price_at(a, d * DAY) / ep.price_at(a, (d - 1) * DAY)) for d in range(1, 150)]
        print(f"  {p:<12} {st.pstdev(r) * 100:5.2f}%")


def chart() -> None:
    e = MarketEngine(World.new(U, SEED, profile="Normal"))
    minutes = list(range(0, 90 * DAY, 30))  # 90 days, sampled every 30 min
    days = [m / DAY for m in minutes]

    picks = [
        ("STOCK", make_asset_id(AssetKind.STOCK, U.stocks[10].symbol), U.stocks[10].name),
        ("CRYPTO", make_asset_id(AssetKind.CRYPTO, "SLR"), "Solaris (crypto)"),
        ("BOND", make_asset_id(AssetKind.BOND, "GOVT-30Y"), "Govt 30Y bond"),
    ]

    fig, axes = plt.subplots(5, 1, figsize=(11, 13), sharex=True)
    for ax, (_, sid, label) in zip(axes[:3], picks):
        ax.plot(days, [e.price_at(sid, m) for m in minutes], lw=0.8)
        ax.set_title(label, fontsize=10, loc="left")
        ax.grid(alpha=0.25)
    axes[3].plot(days, [sentiment_at(SEED, m, 1.0) for m in minutes], color="tab:purple", lw=0.9)
    axes[3].axhline(0, color="grey", lw=0.5)
    axes[3].set_title("Global sentiment  (+greed / -fear)", fontsize=10, loc="left")
    axes[3].grid(alpha=0.25)
    axes[4].plot(days, [interest_rate_at(SEED, m, 0.045, 1.0) * 100 for m in minutes],
                 color="tab:green", lw=0.9)
    axes[4].set_title("Interest rate (%)", fontsize=10, loc="left")
    axes[4].set_xlabel("days")
    axes[4].grid(alpha=0.25)

    fig.suptitle("Trader PRO — V0.3 engine, 90-day sample (Normal profile)", fontsize=12)
    fig.tight_layout()
    out = ROOT / "validation_chart.png"
    fig.savefig(out, dpi=110)
    print(f"\nchart -> {out}")


if __name__ == "__main__":
    stats()
    chart()
