"""Discrete events, shocks, and crash cascades (V1.4) — the drama layer.

Design references: design.md §4.4 (events & shocks), §5.3 (baseline vs deviations).

The baseline engine (V0.3) is a pure function of (world_seed, tick). Events are the
*deviation* layer on top — but we keep them **seeded and deterministic** so the whole
price function stays directly evaluable (fast-forward / replay still free):

  * A world's events are a reproducible schedule generated per day-bucket from the seed.
  * Each event applies a **decaying log-price impact** to its scope (one asset, a sector,
    an asset class, or the whole market). Impact at tick t = severity · exp(−Δt/tau) for
    all events that have already fired, summed over a bounded look-back window.
  * **Cascades**: a black swan doesn't just drop once — when scheduled it spawns a burst of
    correlated *aftershocks* over the following hours/days. Because they're all pre-placed
    in the seeded schedule, the cascade is dramatic *and* still purely evaluable. Player
    margin-call liquidations (orders.liquidate_for_margin) ride on top during the plunge.

Frequency scales with the profile's `event_rate_mult`; black-swan severity and aftershock
count scale with `cascade_mult` (design.md §4.5).
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from .models import SeedUniverse
from .profiles import MarketProfile

DAY = 1440
HOUR = 60
LOOKBACK_DAYS = 75          # window long enough that older shocks have fully decayed


# --------------------------------------------------------------------------- #
# Event record
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class MarketEvent:
    fire_tick: int
    kind: str                 # "earnings", "sector", "class", "rate", "flash_crash", ...
    scope_type: str           # "asset" | "sector" | "class" | "market"
    scope_key: str            # asset_id / sector name / class name / "" for market
    severity: float           # signed log-price impact at the moment of firing
    tau: float                # decay time constant (ticks)
    headline: str

    def impact_at(self, t: int) -> float:
        if t < self.fire_tick:
            return 0.0
        return self.severity * math.exp(-(t - self.fire_tick) / self.tau)


@dataclass(slots=True)
class Impacts:
    """Decayed, summed event impacts at a moment in time, bucketed by scope."""
    market: float = 0.0
    by_class: dict[str, float] = None
    by_sector: dict[str, float] = None
    by_asset: dict[str, float] = None

    def __post_init__(self):
        self.by_class = self.by_class or {}
        self.by_sector = self.by_sector or {}
        self.by_asset = self.by_asset or {}

    def for_asset(self, asset_id: str, asset_class: str, sector: str) -> float:
        return (self.market
                + self.by_class.get(asset_class, 0.0)
                + self.by_sector.get(sector, 0.0)
                + self.by_asset.get(asset_id, 0.0))


# --------------------------------------------------------------------------- #
# Headline flavour
# --------------------------------------------------------------------------- #

_EARNINGS_UP = ["{n} surges on a blowout earnings beat", "{n} pops after raising guidance",
                "Analysts upgrade {n}; shares rally"]
_EARNINGS_DN = ["{n} slides after missing estimates", "{n} sinks on a profit warning",
                "Downgrade hits {n}"]
_SECTOR_UP = ["{k} stocks rally on sector optimism", "Money rotates into {k}"]
_SECTOR_DN = ["{k} names tumble on growth fears", "Selloff sweeps {k}"]
_CRYPTO_UP = ["Crypto frenzy: {n} goes parabolic", "{n} rips higher as inflows surge"]
_CRYPTO_DN = ["{n} craters as leverage unwinds", "{n} dumps on exchange jitters"]
_SWAN = ["BLACK SWAN: liquidity crisis grips markets", "BLACK SWAN: a major fund blows up",
         "BLACK SWAN: contagion fears spark a global selloff", "FLASH CRASH: markets plunge"]
_AFTERSHOCK = ["Aftershock: forced selling drags {k} lower", "Contagion spreads to {k}",
               "Another leg down as margin calls cascade"]


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #

class EventSchedule:
    """Deterministic, seed-driven event generator with a cached per-tick impact sum."""

    def __init__(self, world_seed: int, universe: SeedUniverse, profile: MarketProfile):
        self.seed = world_seed
        self.universe = universe
        self.profile = profile
        self._day_cache: dict[int, list[MarketEvent]] = {}
        self._impact_cache: dict[int, Impacts] = {}
        self._sectors = sorted({s.sector for s in universe.stocks})
        self._stock_ids = [f"STOCK:{s.symbol}" for s in universe.stocks]
        self._crypto_ids = [f"CRYPTO:{c.symbol}" for c in universe.crypto]
        self._name = {f"STOCK:{s.symbol}": s.name for s in universe.stocks}
        self._name.update({f"CRYPTO:{c.symbol}": c.name for c in universe.crypto})

    # ---- deterministic per-day generation ---- #

    def _rng(self, day: int, salt: str) -> random.Random:
        h = hashlib.md5(f"{self.seed}|ev|{salt}|{day}".encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def _events_for_day(self, day: int) -> list[MarketEvent]:
        if day in self._day_cache:
            return self._day_cache[day]
        evs: list[MarketEvent] = []
        er = self.profile.event_rate_mult
        cm = self.profile.cascade_mult
        base = day * DAY

        # --- micro: single-asset earnings / crypto moves (a few per day) ---
        r = self._rng(day, "micro")
        n_micro = _poisson(r, 1.8 * er)
        for _ in range(n_micro):
            if r.random() < 0.78 and self._stock_ids:        # stock earnings
                aid = r.choice(self._stock_ids)
                up = r.random() < 0.5
                sev = (1 if up else -1) * abs(r.gauss(0, 0.05))
                head = r.choice(_EARNINGS_UP if up else _EARNINGS_DN).format(n=self._name[aid])
                tau = r.uniform(0.5, 2.0) * DAY
                kind = "earnings"
            else:                                            # crypto move
                aid = r.choice(self._crypto_ids)
                up = r.random() < 0.5
                sev = (1 if up else -1) * abs(r.gauss(0, 0.12))
                head = r.choice(_CRYPTO_UP if up else _CRYPTO_DN).format(n=self._name[aid])
                tau = r.uniform(0.5, 3.0) * DAY
                kind = "crypto"
            evs.append(MarketEvent(base + r.randint(0, DAY - 1), kind, "asset", aid, sev, tau, head))

        # --- macro: sector rotations (occasional) ---
        r = self._rng(day, "macro")
        if r.random() < 0.11 * er and self._sectors:
            sector = r.choice(self._sectors)
            up = r.random() < 0.5
            sev = (1 if up else -1) * abs(r.gauss(0, 0.05))
            head = r.choice(_SECTOR_UP if up else _SECTOR_DN).format(k=sector)
            evs.append(MarketEvent(base + r.randint(0, DAY - 1), "sector", "sector", sector,
                                   sev, r.uniform(2, 6) * DAY, head))

        # --- black swan: rare, severe, with a cascade of aftershocks ---
        r = self._rng(day, "swan")
        swan_prob = 0.004 * er * cm
        if r.random() < swan_prob:
            fire = base + r.randint(0, DAY - 1)
            severity = -abs(r.gauss(0.22, 0.06)) * cm      # deep market drop
            tau = r.uniform(10, 25) * DAY                  # slow, partial recovery
            evs.append(MarketEvent(fire, "flash_crash", "market", "", severity, tau,
                                   r.choice(_SWAN)))
            # aftershocks: correlated secondary drops over the following days
            n_after = int(r.uniform(3, 7) * cm)
            for _ in range(n_after):
                dt = int(abs(r.gauss(0, 1.5)) * DAY) + r.randint(0, DAY)
                if r.random() < 0.5 and self._sectors:
                    stype, skey = "sector", r.choice(self._sectors)
                    head = r.choice(_AFTERSHOCK).format(k=skey)
                else:
                    stype, skey = "class", r.choice(["CRYPTO", "STOCK"])
                    head = r.choice(_AFTERSHOCK).format(k=skey.lower())
                sev = -abs(r.gauss(0.08, 0.03)) * cm
                evs.append(MarketEvent(fire + dt, "aftershock", stype, skey, sev,
                                       r.uniform(3, 10) * DAY, head))

        evs.sort(key=lambda e: e.fire_tick)
        self._day_cache[day] = evs
        return evs

    # ---- impact summation (cached per tick) ---- #

    def impacts_at(self, t: int) -> Impacts:
        if t in self._impact_cache:
            return self._impact_cache[t]
        imp = Impacts()
        day = t // DAY
        for d in range(max(0, day - LOOKBACK_DAYS), day + 1):
            for ev in self._events_for_day(d):
                if ev.fire_tick > t:
                    continue
                val = ev.impact_at(t)
                if abs(val) < 1e-6:
                    continue
                if ev.scope_type == "market":
                    imp.market += val
                elif ev.scope_type == "class":
                    imp.by_class[ev.scope_key] = imp.by_class.get(ev.scope_key, 0.0) + val
                elif ev.scope_type == "sector":
                    imp.by_sector[ev.scope_key] = imp.by_sector.get(ev.scope_key, 0.0) + val
                else:
                    imp.by_asset[ev.scope_key] = imp.by_asset.get(ev.scope_key, 0.0) + val
        if len(self._impact_cache) > 512:
            self._impact_cache.clear()
        self._impact_cache[t] = imp
        return imp

    def fired_between(self, t0: int, t1: int) -> list[MarketEvent]:
        """Events whose fire_tick is in (t0, t1] — i.e. what just happened on an advance."""
        out: list[MarketEvent] = []
        for d in range(max(0, t0 // DAY), t1 // DAY + 1):
            for ev in self._events_for_day(d):
                if t0 < ev.fire_tick <= t1:
                    out.append(ev)
        out.sort(key=lambda e: (abs(e.severity)), reverse=True)
        return out

    # ---- news feed ---- #

    def recent(self, t: int, lookback_days: int = 10, limit: int = 12) -> list[MarketEvent]:
        day = t // DAY
        out: list[MarketEvent] = []
        for d in range(max(0, day - lookback_days), day + 1):
            for ev in self._events_for_day(d):
                if ev.fire_tick <= t:
                    out.append(ev)
        out.sort(key=lambda e: e.fire_tick, reverse=True)
        return out[:limit]


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's Poisson sampler (lam is small here)."""
    if lam <= 0:
        return 0
    el = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= el:
            return k - 1
