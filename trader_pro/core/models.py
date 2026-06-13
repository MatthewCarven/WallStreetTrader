"""Seed-data record types and loader.

These describe the *immutable starting universe* of a world — the assets that exist and
their baseline parameters. They are intentionally separate from live, changing state
(current prices, sentiment, portfolios), which the simulation engine owns from V0.2 on.

Design references: design.md §3 (asset classes), §4.1 (price forces), §7.1 (seed data).

All numbers are deliberately ballpark — the seed only has to be *plausible*; the
simulation produces the interesting behaviour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# Seed record types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class StockSeed:
    """A single equity in the starting universe."""

    symbol: str
    name: str
    sector: str
    sub_industry: str
    fair_value: float        # baseline share price the sim mean-reverts toward
    growth_rate: float       # annualised fundamental drift (e.g. 0.08 = +8%/yr)
    volatility: float        # annualised volatility (e.g. 0.30 = 30%)
    market_cap: float        # ballpark, in USD

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "StockSeed":
        return StockSeed(**d)


@dataclass(frozen=True, slots=True)
class BondSeed:
    """A fixed-income instrument. Price moves inversely to the global rate level."""

    id: str
    name: str
    issuer_type: str         # "government" | "corporate"
    rating: str              # AAA, AA, A, BBB, BB, B, CCC ...
    face_value: float        # redemption value (typically 1000)
    coupon_rate: float       # annual coupon as a fraction of face (e.g. 0.045)
    maturity_years: float    # years to maturity
    base_yield: float        # baseline yield-to-maturity at world start
    default_prob: float      # annualised probability of default (drives crash risk)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BondSeed":
        return BondSeed(**d)


@dataclass(frozen=True, slots=True)
class CryptoSeed:
    """A fictional crypto asset. Weak fundamental anchor, high noise (design.md §3.3)."""

    symbol: str
    name: str
    archetype: str           # e.g. "store-of-value", "platform", "meme", "stablecoin"
    fair_value: float        # weak anchor; the sim lets price wander far from it
    volatility: float        # annualised volatility (high: 0.6 .. 1.5)
    fundamental_strength: float  # 0..1 — how strongly the weak anchor pulls
    circulating_supply: float

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "CryptoSeed":
        return CryptoSeed(**d)


# --------------------------------------------------------------------------- #
# Universe container + loader
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class SeedUniverse:
    """The full immutable starting universe, loaded from the seed JSON files."""

    stocks: tuple[StockSeed, ...]
    bonds: tuple[BondSeed, ...]
    crypto: tuple[CryptoSeed, ...]

    def summary(self) -> str:
        return (
            f"SeedUniverse: {len(self.stocks)} stocks, "
            f"{len(self.bonds)} bonds, {len(self.crypto)} crypto"
        )


# Default location of the generated seed files: <repo>/data/seeds
DEFAULT_SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seeds"


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_seed_universe(seed_dir: Path | str = DEFAULT_SEED_DIR) -> SeedUniverse:
    """Load the seed universe from the generated JSON files.

    Raises FileNotFoundError with a helpful hint if the seeds haven't been built yet.
    """
    seed_dir = Path(seed_dir)
    missing = [
        name
        for name in ("stocks.json", "bonds.json", "crypto.json")
        if not (seed_dir / name).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing seed files {missing} in {seed_dir}. "
            f"Run `python scripts/build_seed.py` to generate them."
        )

    stocks = tuple(StockSeed.from_dict(d) for d in _load_json(seed_dir / "stocks.json"))
    bonds = tuple(BondSeed.from_dict(d) for d in _load_json(seed_dir / "bonds.json"))
    crypto = tuple(CryptoSeed.from_dict(d) for d in _load_json(seed_dir / "crypto.json"))
    return SeedUniverse(stocks=stocks, bonds=bonds, crypto=crypto)


def record_to_dict(record: Any) -> dict[str, Any]:
    """Serialize a seed record back to a plain dict (used by the generator)."""
    return asdict(record)
