"""Buyable predictions (V1.5) — a paid, probabilistic peek at the future (design.md §5.4).

Because prices are deterministic, the *true* future price is knowable. A prediction reveals
a **noised** version of it: the noise shrinks with the world's `predictability` (so Calm
worlds give sharp forecasts and Apocalyptic ones give a fuzzy lean) and grows with the
horizon. The noise is seeded by (world_seed, buy_tick, asset, horizon), so buying the same
peek twice — or reloading — gives the same answer (no save-scumming a reroll).

Cost scales with information scarcity: heavily-covered mega-caps are cheap and reliable;
small/obscure names and crypto cost more (but a correct call there pays off bigger).
"""

from __future__ import annotations

import hashlib
import math
import statistics as st
from dataclasses import dataclass

from .world import AssetKind, World

DAY = 1440
BASE_COST = 20.0
BASE_SIGMA = 0.16          # forecast noise at predictability 0, 1-day horizon

# Median-ish reference market cap for the obscurity cost curve.
_REF_CAP = 1.5e11


@dataclass(frozen=True, slots=True)
class Prediction:
    asset_id: str
    horizon: int            # ticks ahead
    current: float
    forecast: float         # noised predicted price at buy_tick + horizon
    sigma: float            # ~1σ relative uncertainty
    cost: float
    confidence: float       # 0..1 (= world predictability), shown to the player

    @property
    def direction(self) -> str:
        return "UP" if self.forecast >= self.current else "DOWN"

    @property
    def low(self) -> float:
        return self.forecast * math.exp(-self.sigma)

    @property
    def high(self) -> float:
        return self.forecast * math.exp(self.sigma)


def _obscurity_factor(world: World, asset_id: str) -> float:
    kind = world.kind_of(asset_id)
    meta = world.meta_of(asset_id)
    if kind is AssetKind.STOCK:
        # big cap -> well covered -> cheap; small cap -> dear
        return min(4.0, max(0.5, (_REF_CAP / max(meta.market_cap, 1e8)) ** 0.25))
    if kind is AssetKind.CRYPTO:
        return 2.5            # crypto: less coverage, pricier
    return 0.5               # bonds: very predictable, cheap


def quote_cost(world: World, asset_id: str, horizon: int) -> float:
    horizon_days = horizon / DAY
    return round(BASE_COST * _obscurity_factor(world, asset_id) * (1.0 + 0.12 * horizon_days), 2)


def make_prediction(world: World, engine, asset_id: str, horizon: int) -> Prediction:
    """Build (but do not charge for) a prediction. The CLI handles payment."""
    from .profiles import get_profile
    t = world.market.tick_index
    predictability = get_profile(world.config.profile).predictability
    current = world.price(asset_id)
    true_future = engine.price_at(asset_id, t + horizon)

    horizon_days = max(0.5, horizon / DAY)
    sigma = BASE_SIGMA * (1.0 - predictability) * math.sqrt(horizon_days)

    # Seeded noise so the peek is stable for this (world, tick, asset, horizon).
    h = hashlib.md5(f"{world.config.world_seed}|pred|{t}|{asset_id}|{horizon}".encode()).hexdigest()
    u1 = (int(h[0:8], 16) + 1) / (0xFFFFFFFF + 2)
    u2 = (int(h[8:16], 16) + 1) / (0xFFFFFFFF + 2)
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    forecast = true_future * math.exp(z * sigma)

    return Prediction(
        asset_id=asset_id, horizon=horizon, current=current, forecast=forecast,
        sigma=sigma, cost=quote_cost(world, asset_id, horizon), confidence=predictability,
    )
