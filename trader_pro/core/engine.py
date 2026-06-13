"""The layered tick engine (V0.3) — where the market comes alive.

Design references: design.md §4 (price forces), §4.5 (volatility profiles), §5 (the
layered, seeded time model).

Core idea
---------
Every price is a **pure, deterministic function of (world_seed, tick)**. We build it from
*layered value noise*: for each time layer (Minute → Hour → Session → Cycle → Era) we draw
seeded random "anchors" at that layer's period and smoothly interpolate between them. Sum
the layers and you get a signal that is:

  * noisy minute-to-minute,
  * trending over days/weeks (the slow layers),
  * naturally **mean-reverting** to the asset's fundamental (the noise is centred on 0),
  * and **directly evaluable at any tick** — so fast-forward and replay are free
    (design.md §5.2). No tick-by-tick iteration required.

The "green early, tank into the close" mechanic (design.md §5) falls straight out of the
Hour layer: the price the hour is heading toward is the Hour anchor at the next hour
boundary, decided in advance — the Minute layer just wobbles around the path to it.

Scope (V0.3): the directly-evaluable *baseline* — drift, multi-scale idiosyncratic noise,
a global sentiment factor, sector trends, and an evolving interest rate that prices bonds.
The *deviation* layer that needs iteration — momentum feedback, discrete events, and crash
cascades (design.md §4.4, §5.3) — arrives in V1.4 and layers on top of this.

1 tick = 1 simulated minute.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .models import BondSeed, CryptoSeed, StockSeed
from .world import AssetKind, World
from .profiles import MarketProfile, get_profile, PROFILE_BY_NAME

# --------------------------------------------------------------------------- #
# Time layers (periods in ticks/minutes)
# --------------------------------------------------------------------------- #

MINUTE = 1
HOUR = 60
DAY = 1440                 # 24h — the world runs continuously (crypto-style)
WEEK = 7 * DAY             # 10_080
YEAR = 365 * DAY           # 525_600


# The price signal is split into two pieces so daily/weekly/yearly magnitudes all come
# out realistic at once (design.md §5.1):
#
#   * SLOW WANDER — the Era/Cycle/Session layers, with Brownian amplitude (∝ √period).
#     This makes variance accumulate over time like a real random walk: a ~0.30-vol asset
#     moves ~2%/day, ~6%/week, and wanders tens-of-percent over a year, while still
#     mean-reverting to its fundamental (the noise is centred).
#
#   * INTRADAY WOBBLE — a small, bounded Hour+Minute oscillation that does NOT accumulate
#     into the daily/yearly figures, but gives the live minute-by-minute motion and the
#     "green early, tank into the close" hour mechanic (design.md §5).
#
# Slow layers and their periods (ticks). Amplitudes are derived as √(period / YEAR).
SLOW_PERIODS: tuple[int, ...] = (YEAR, WEEK, DAY)

# Intraday oscillation: relative weights of the hour and minute layers, and the overall
# intraday amplitude as a fraction of the asset's volatility.
INTRADAY_HOUR_WEIGHT = 1.0
INTRADAY_MINUTE_WEIGHT = 0.4
INTRADAY_AMPLITUDE = 0.045

# Master amplitude on the slow wander: 1.0 means the year-scale log deviation ≈ the
# asset's annualised volatility. Tuned in V0.4.
MASTER_AMPLITUDE = 0.8

# --------------------------------------------------------------------------- #
# Volatility profiles (design.md §4.5) are defined in profiles.py (V0.5).
# Back-compat: a profile is duck-typed by .vol_mult / .sentiment_mult / .rate_mult,
# so the existing price functions keep working unchanged.
ProfileCoeffs = MarketProfile
PROFILE_COEFFS = PROFILE_BY_NAME

# --------------------------------------------------------------------------- #
# Seeded value-noise primitives (pure functions of the key + tick)
# --------------------------------------------------------------------------- #

def _anchor(world_seed: int, key: str, idx: int) -> float:
    """A reproducible standard-normal draw for segment `idx` of signal `key`."""
    h = hashlib.md5(f"{world_seed}|{key}|{idx}".encode("utf-8")).hexdigest()
    # Two independent uniforms -> Box–Muller -> one N(0,1).
    u1 = (int(h[0:8], 16) + 1) / (0xFFFFFFFF + 2)
    u2 = (int(h[8:16], 16) + 1) / (0xFFFFFFFF + 2)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _smoothstep(x: float) -> float:
    return x * x * (3.0 - 2.0 * x)


def value_noise(world_seed: int, key: str, t: float, period: float) -> float:
    """Smoothly-interpolated seeded noise; a continuous pure function of `t`."""
    pos = t / period
    i = math.floor(pos)
    frac = pos - i
    a = _anchor(world_seed, key, i)
    b = _anchor(world_seed, key, i + 1)
    return a + (b - a) * _smoothstep(frac)


def slow_noise(world_seed: int, key: str, t: float) -> float:
    """Brownian-scaled slow wander (Era/Cycle/Session). Amplitude ∝ √period, so variance
    accumulates over time like a random walk while staying centred (mean-reverting)."""
    total = 0.0
    for period in SLOW_PERIODS:
        weight = math.sqrt(period / YEAR)
        total += weight * value_noise(world_seed, f"{key}|slow{period}", t, period)
    return total


def intraday_noise(world_seed: int, key: str, t: float) -> float:
    """Small bounded hour+minute oscillation for live motion and the hour mechanic."""
    return (
        INTRADAY_HOUR_WEIGHT * value_noise(world_seed, f"{key}|hour", t, HOUR)
        + INTRADAY_MINUTE_WEIGHT * value_noise(world_seed, f"{key}|min", t, 3)
    )


def asset_log_noise(world_seed: int, key: str, t: float, vol: float, vol_mult: float) -> float:
    """Total idiosyncratic log-price noise for an asset: slow wander + intraday wobble,
    scaled by the asset's volatility and the world's profile multiplier."""
    slow = MASTER_AMPLITUDE * slow_noise(world_seed, key, t)
    intra = INTRADAY_AMPLITUDE * intraday_noise(world_seed, key, t)
    return vol * vol_mult * (slow + intra)


# --------------------------------------------------------------------------- #
# Global factors (shared across assets -> correlation, design.md §4.2–4.3)
# --------------------------------------------------------------------------- #

def sentiment_at(world_seed: int, t: float, mult: float = 1.0) -> float:
    """Global risk mood in [-1, 1]; slow (cycle/era scale). +greed / -fear."""
    raw = (
        0.7 * value_noise(world_seed, "__sentiment__|cycle", t, WEEK)
        + 0.5 * value_noise(world_seed, "__sentiment__|era", t, YEAR)
    )
    return math.tanh(raw * mult)


def interest_rate_at(world_seed: int, t: float, base: float, mult: float = 1.0) -> float:
    """Global interest-rate level, drifting slowly around `base`."""
    swing = 0.020 * mult * value_noise(world_seed, "__rate__", t, YEAR)
    # A gentle multi-month wobble on top.
    swing += 0.006 * mult * value_noise(world_seed, "__rate__|q", t, 90 * DAY)
    return max(0.0, base + swing)


def sector_trend_at(world_seed: int, sector: str, t: float) -> float:
    """Per-sector rotation factor (~weeks). Drives 'tech is hot' style moves."""
    return value_noise(world_seed, f"__sector__|{sector}", t, WEEK)


# --------------------------------------------------------------------------- #
# Per-asset price models
# --------------------------------------------------------------------------- #

# How strongly each kind responds to the global mood and to sector rotation.
SENTIMENT_BETA = {AssetKind.STOCK: 0.18, AssetKind.CRYPTO: 0.45, AssetKind.BOND: -0.06}
SECTOR_BETA = 0.10


def _years(t: float) -> float:
    return t / YEAR


def stock_price_at(world_seed: int, s: StockSeed, t: float, coeffs: ProfileCoeffs) -> float:
    aid = f"STOCK:{s.symbol}"
    drift = s.growth_rate * _years(t)
    noise = asset_log_noise(world_seed, aid, t, s.volatility, coeffs.vol_mult)
    senti = SENTIMENT_BETA[AssetKind.STOCK] * sentiment_at(world_seed, t, coeffs.sentiment_mult)
    sect = SECTOR_BETA * sector_trend_at(world_seed, s.sector, t)
    log_price = math.log(s.fair_value) + drift + noise + senti + sect
    return math.exp(log_price)


def crypto_price_at(world_seed: int, c: CryptoSeed, t: float, coeffs: ProfileCoeffs) -> float:
    aid = f"CRYPTO:{c.symbol}"
    # Weak fundamental anchor: a slow idiosyncratic drift lets price detach for long
    # stretches, scaled down by fundamental_strength (stronger anchor -> less detachment).
    detach = (1.0 - c.fundamental_strength) * 0.9 * value_noise(world_seed, f"{aid}|detach", t, YEAR)
    noise = asset_log_noise(world_seed, aid, t, c.volatility, coeffs.vol_mult)
    senti = (SENTIMENT_BETA[AssetKind.CRYPTO] * (1.0 - c.fundamental_strength)
             * sentiment_at(world_seed, t, coeffs.sentiment_mult))
    log_price = math.log(c.fair_value) + detach + noise + senti
    return math.exp(log_price)


def bond_price_at(
    world_seed: int, b: BondSeed, t: float, base_rate: float, coeffs: ProfileCoeffs
) -> float:
    """Present value of remaining cashflows at the current yield (rate + credit spread)."""
    years_remaining = b.maturity_years - _years(t)
    if years_remaining <= 0:
        return b.face_value  # redeemed at par

    credit_spread = b.base_yield - base_rate          # locked-in spread over the curve
    rate_now = interest_rate_at(world_seed, t, base_rate, coeffs.rate_mult)
    ytm = max(0.001, rate_now + credit_spread)

    n = max(1, math.ceil(years_remaining))
    coupon = b.coupon_rate * b.face_value
    pv = sum(coupon / (1 + ytm) ** k for k in range(1, n + 1))
    pv += b.face_value / (1 + ytm) ** n
    return pv


# --------------------------------------------------------------------------- #
# The engine: stateless over a World (all state lives in world_seed + tick)
# --------------------------------------------------------------------------- #

class MarketEngine:
    """Drives a World's prices. Holds no state of its own beyond config — everything is
    derived from the world's seed and tick, so nothing extra needs serializing."""

    def __init__(self, world: World, *, base_rate: float | None = None):
        self.world = world
        self.coeffs = get_profile(world.config.profile)
        self.base_rate = base_rate if base_rate is not None else world.market.interest_rate
        self.recompute()

    # ---- price evaluation ---- #

    def price_at(self, asset_id: str, t: int) -> float:
        kind = self.world.kind_of(asset_id)
        meta = self.world.meta_of(asset_id)
        seed = self.world.config.world_seed
        if kind is AssetKind.STOCK:
            return stock_price_at(seed, meta, t, self.coeffs)
        if kind is AssetKind.CRYPTO:
            return crypto_price_at(seed, meta, t, self.coeffs)
        return bond_price_at(seed, meta, t, self.base_rate, self.coeffs)

    def recompute(self) -> None:
        """Re-evaluate every global factor and price at the world's current tick."""
        w = self.world
        t = w.market.tick_index
        seed = w.config.world_seed
        w.market.interest_rate = interest_rate_at(seed, t, self.base_rate, self.coeffs.rate_mult)
        w.market.sentiment = sentiment_at(seed, t, self.coeffs.sentiment_mult)
        prices = w.market.prices
        for aid in w.asset_ids():
            prices[aid] = self.price_at(aid, t)

    def advance(self, n: int = 1) -> None:
        """Advance the clock by `n` ticks and recompute prices."""
        self.world.advance_tick(n)
        self.recompute()

    def advance_to(self, tick: int) -> None:
        """Jump directly to `tick` (fast-forward / resume). O(assets), not O(ticks)."""
        if tick < self.world.market.tick_index:
            raise ValueError("cannot move the clock backwards")
        self.world.market.tick_index = tick
        self.recompute()

    def series(self, asset_id: str, start: int, end: int, step: int = 1) -> list[tuple[int, float]]:
        """A price path for one asset over [start, end) - for charts/validation."""
        return [(t, self.price_at(asset_id, t)) for t in range(start, end, step)]
