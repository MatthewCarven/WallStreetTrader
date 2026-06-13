#!/usr/bin/env python3
"""Tiny smoke demo of the V0.2 world model.

    python scripts/demo_world.py

Creates a world, buys a few assets, advances the clock, saves & reloads, and prints the
account. Prices don't move yet — that's the V0.3 engine — so this just proves the plumbing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.core import (  # noqa: E402
    load_seed_universe, World, Order, OrderSide, execute_order,
    AssetKind, make_asset_id, save_world, load_world,
)


def main() -> None:
    universe = load_seed_universe()
    print(universe.summary())

    world = World.new(universe, world_seed=20260614, profile="Normal", starting_cash=2500.0)
    print(f"\nNew world | profile={world.config.profile} "
          f"cash=${world.portfolio.cash:,.2f} assets={len(world.asset_ids())}")

    # Buy one of each kind (first asset of each).
    picks = [
        make_asset_id(AssetKind.STOCK, universe.stocks[0].symbol),
        make_asset_id(AssetKind.BOND, universe.bonds[0].id),
        make_asset_id(AssetKind.CRYPTO, universe.crypto[5].symbol),  # a cheap meme coin
    ]
    for aid in picks:
        price = world.price(aid)
        qty = max(1.0, round((300.0 / price), 4))  # ~$300 each
        res = execute_order(world, Order(aid, OrderSide.BUY, qty))
        flag = "OK " if res.filled else "XX "
        print(f"  {flag}BUY {qty:>10} {world.name_of(aid):<26} @ ${price:<12,.4f} "
              f"-> {res.message}")

    world.advance_tick(60)  # one simulated hour of clock (no price move yet)
    print(f"\nAfter trades: cash=${world.portfolio.cash:,.2f} "
          f"equity=${world.equity():,.2f} tick={world.market.tick_index}")

    # Save & reload to prove the state round-trips.
    save_path = ROOT / "saves" / "demo.world"
    save_world(world, save_path)
    reloaded = load_world(save_path, universe)
    ok = reloaded.to_dict() == world.to_dict()
    print(f"Saved -> {save_path}")
    print(f"Reloaded & identical: {ok}")


if __name__ == "__main__":
    main()
