"""The live world model (V0.2).

A `World` bundles everything that defines one playable market at one moment in time:

    * the immutable seed universe (assets + their baseline parameters),
    * a `WorldConfig` (seed, volatility profile, starting cash),
    * a `MarketState` (current prices, global rate & sentiment, the tick clock),
    * the player `Portfolio`.

The whole live state serializes to a single JSON blob (design.md §6.1, §7.2): "save game"
and "sync to server" are the same operation. The static asset metadata is *not* embedded
— it's reloaded from the deterministic seed files, since any world with the same seed
shares the same universe.

The price-evolution engine (the layered tick model, design.md §5) arrives in V0.3. Here,
`advance_tick()` only ticks the clock; prices hold at their seeded starting values.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .models import SeedUniverse, load_seed_universe
from .portfolio import Portfolio

SCHEMA_VERSION = 1

# The 8-point volatility scale (design.md §4.5) lives in profiles.py (single source of
# truth). Re-exported here as PROFILES for convenience/back-compat.
from .profiles import PROFILE_NAMES as PROFILES, DEFAULT_PROFILE  # noqa: E402

DEFAULT_STARTING_CASH = 2500.0      # design.md §8.2
DEFAULT_INTEREST_RATE = 0.045       # baseline global rate level
DEFAULT_SENTIMENT = 0.0             # -1 (fear) .. +1 (greed)


class AssetKind(str, Enum):
    STOCK = "STOCK"
    BOND = "BOND"
    CRYPTO = "CRYPTO"


def make_asset_id(kind: AssetKind, code: str) -> str:
    return f"{kind.value}:{code}"


# --------------------------------------------------------------------------- #
# Config & market state
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class WorldConfig:
    world_seed: int
    profile: str = "Normal"
    starting_cash: float = DEFAULT_STARTING_CASH
    fee_level: str = "off"

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise ValueError(f"unknown profile {self.profile!r}; choose from {PROFILES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_seed": self.world_seed,
            "profile": self.profile,
            "starting_cash": self.starting_cash,
            "fee_level": self.fee_level,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "WorldConfig":
        return WorldConfig(
            world_seed=d["world_seed"],
            profile=d.get("profile", "Normal"),
            starting_cash=d.get("starting_cash", DEFAULT_STARTING_CASH),
            fee_level=d.get("fee_level", "off"),
        )


@dataclass(slots=True)
class MarketState:
    tick_index: int = 0
    interest_rate: float = DEFAULT_INTEREST_RATE
    sentiment: float = DEFAULT_SENTIMENT
    prices: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_index": self.tick_index,
            "interest_rate": self.interest_rate,
            "sentiment": self.sentiment,
            "prices": self.prices,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MarketState":
        return MarketState(
            tick_index=d.get("tick_index", 0),
            interest_rate=d.get("interest_rate", DEFAULT_INTEREST_RATE),
            sentiment=d.get("sentiment", DEFAULT_SENTIMENT),
            prices=dict(d.get("prices", {})),
        )


# --------------------------------------------------------------------------- #
# World
# --------------------------------------------------------------------------- #

@dataclass
class World:
    universe: SeedUniverse
    config: WorldConfig
    market: MarketState
    portfolio: Portfolio

    # Derived registries (rebuilt from the universe, never serialized).
    _kind: dict[str, AssetKind] = field(default_factory=dict, repr=False)
    _name: dict[str, str] = field(default_factory=dict, repr=False)
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def new(
        cls,
        universe: SeedUniverse,
        world_seed: int,
        *,
        profile: str = "Normal",
        starting_cash: float = DEFAULT_STARTING_CASH,
        fee_level: str = "off",
    ) -> "World":
        """Create a fresh world at tick 0 with seeded starting prices."""
        config = WorldConfig(world_seed=world_seed, profile=profile,
                             starting_cash=starting_cash, fee_level=fee_level)
        market = MarketState()
        portfolio = Portfolio(cash=starting_cash)
        world = cls(universe=universe, config=config, market=market, portfolio=portfolio)
        world._build_registry()
        world._seed_initial_prices()
        return world

    def _build_registry(self) -> None:
        self._kind.clear(); self._name.clear(); self._meta.clear()
        for s in self.universe.stocks:
            aid = make_asset_id(AssetKind.STOCK, s.symbol)
            self._kind[aid] = AssetKind.STOCK
            self._name[aid] = s.name
            self._meta[aid] = s
        for b in self.universe.bonds:
            aid = make_asset_id(AssetKind.BOND, b.id)
            self._kind[aid] = AssetKind.BOND
            self._name[aid] = b.name
            self._meta[aid] = b
        for c in self.universe.crypto:
            aid = make_asset_id(AssetKind.CRYPTO, c.symbol)
            self._kind[aid] = AssetKind.CRYPTO
            self._name[aid] = c.name
            self._meta[aid] = c

    def _seed_initial_prices(self) -> None:
        for s in self.universe.stocks:
            self.market.prices[make_asset_id(AssetKind.STOCK, s.symbol)] = s.fair_value
        for b in self.universe.bonds:
            # Issued at par; rate-sensitivity arrives with the engine (V0.3).
            self.market.prices[make_asset_id(AssetKind.BOND, b.id)] = b.face_value
        for c in self.universe.crypto:
            self.market.prices[make_asset_id(AssetKind.CRYPTO, c.symbol)] = c.fair_value

    # ------------------------------------------------------------------ #
    # Asset access
    # ------------------------------------------------------------------ #

    def asset_ids(self) -> list[str]:
        return list(self._kind.keys())

    def has_asset(self, asset_id: str) -> bool:
        return asset_id in self._kind

    def kind_of(self, asset_id: str) -> AssetKind:
        return self._kind[asset_id]

    def name_of(self, asset_id: str) -> str:
        return self._name[asset_id]

    def meta_of(self, asset_id: str) -> Any:
        """The underlying seed record (StockSeed / BondSeed / CryptoSeed)."""
        return self._meta[asset_id]

    def price(self, asset_id: str) -> float:
        return self.market.prices[asset_id]

    @property
    def price_of(self) -> Callable[[str], float]:
        return lambda aid: self.market.prices[aid]

    # ------------------------------------------------------------------ #
    # Clock & valuation
    # ------------------------------------------------------------------ #

    def advance_tick(self, n: int = 1) -> None:
        """Advance the clock. V0.2: clock only. V0.3 plugs the layered engine in here."""
        if n < 0:
            raise ValueError("cannot advance a negative number of ticks")
        self.market.tick_index += n

    def equity(self) -> float:
        return self.portfolio.equity(self.price_of)

    def net_worth(self) -> float:
        """Equity minus outstanding loan debt (design.md §8.2)."""
        return self.portfolio.net_worth(self.price_of)

    def derive_rng(self, salt: str) -> random.Random:
        """A deterministic RNG stream bound to (world_seed, tick, salt). Engine seam."""
        import hashlib
        key = f"{self.config.world_seed}:{self.market.tick_index}:{salt}"
        h = hashlib.md5(key.encode("utf-8")).hexdigest()
        return random.Random(int(h[:16], 16))

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "config": self.config.to_dict(),
            "market": self.market.to_dict(),
            "portfolio": self.portfolio.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], universe: SeedUniverse) -> "World":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {data.get('schema_version')} "
                f"(expected {SCHEMA_VERSION})"
            )
        world = cls(
            universe=universe,
            config=WorldConfig.from_dict(data["config"]),
            market=MarketState.from_dict(data["market"]),
            portfolio=Portfolio.from_dict(data["portfolio"]),
        )
        world._build_registry()
        # Backfill any prices missing from the blob (e.g. assets added to the seed
        # since the save) so the world is always fully priced.
        for aid in world._kind:
            world.market.prices.setdefault(aid, world._starting_price(aid))
        return world

    def _starting_price(self, asset_id: str) -> float:
        meta = self._meta[asset_id]
        kind = self._kind[asset_id]
        if kind is AssetKind.BOND:
            return meta.face_value
        return meta.fair_value


# --------------------------------------------------------------------------- #
# Save / load helpers
# --------------------------------------------------------------------------- #

def save_world(world: World, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(world.to_dict(), fh, indent=2)
        fh.write("\n")


def load_world(path: Path | str, universe: SeedUniverse | None = None) -> World:
    """Load a saved world. If `universe` is None, reload it from the default seed files."""
    if universe is None:
        universe = load_seed_universe()
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return World.from_dict(data, universe)
