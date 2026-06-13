#!/usr/bin/env python3
"""Build the Trader PRO seed universe (deterministic).

Reads the raw S&P 500 constituents CSV and writes three seed files:

    data/seeds/stocks.json   — one record per S&P 500 company
    data/seeds/bonds.json    — a generated government + corporate bond ladder
    data/seeds/crypto.json   — a hand-authored set of fictional coins

Everything is seeded from SEED below, so the starting universe is reproducible
(design.md §5.2, §7.1). Seed numbers are deliberately ballpark — only plausibility
matters; the simulation engine produces the real behaviour.

Usage:
    python scripts/build_seed.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path

# Repo root = parent of this script's directory (scripts/..)
ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "sp500_constituents.csv"
SEED_DIR = ROOT / "data" / "seeds"

SEED = 20260614  # world-build seed; change to reshuffle the starting universe


# --------------------------------------------------------------------------- #
# Deterministic per-asset RNG
# --------------------------------------------------------------------------- #

def rng_for(key: str, salt: str) -> random.Random:
    """A stable, per-key Random stream (hashlib, so it's reproducible across runs)."""
    h = hashlib.md5(f"{SEED}:{salt}:{key}".encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def log_uniform(rng: random.Random, lo: float, hi: float) -> float:
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Stocks
# --------------------------------------------------------------------------- #

# Per-GICS-sector baselines: (annual growth mean, annual volatility mean).
SECTOR_PROFILE: dict[str, tuple[float, float]] = {
    "Information Technology":   (0.13, 0.34),
    "Communication Services":  (0.09, 0.28),
    "Consumer Discretionary":  (0.09, 0.30),
    "Health Care":             (0.09, 0.22),
    "Financials":              (0.07, 0.26),
    "Industrials":             (0.07, 0.24),
    "Materials":               (0.06, 0.26),
    "Real Estate":             (0.05, 0.24),
    "Consumer Staples":        (0.05, 0.18),
    "Energy":                  (0.05, 0.34),
    "Utilities":               (0.04, 0.18),
}
DEFAULT_SECTOR = (0.07, 0.26)


def build_stocks() -> list[dict]:
    rows: list[dict] = []
    with CSV_PATH.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = (row.get("Symbol") or "").strip()
            name = (row.get("Security") or "").strip()
            sector = (row.get("GICS Sector") or "").strip()
            sub = (row.get("GICS Sub-Industry") or "").strip()
            if not symbol or not name:
                continue

            g_mean, v_mean = SECTOR_PROFILE.get(sector, DEFAULT_SECTOR)
            r = rng_for(symbol, "stock")

            fair_value = round(log_uniform(r, 8, 650), 2)
            market_cap = round(log_uniform(r, 3e9, 2.5e12), -6)
            growth_rate = round(clamp(r.gauss(g_mean, 0.04), -0.05, 0.25), 4)
            volatility = round(clamp(r.gauss(v_mean, 0.05), 0.10, 0.70), 4)

            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "sector": sector,
                    "sub_industry": sub,
                    "fair_value": fair_value,
                    "growth_rate": growth_rate,
                    "volatility": volatility,
                    "market_cap": market_cap,
                }
            )
    rows.sort(key=lambda d: d["symbol"])
    return rows


# --------------------------------------------------------------------------- #
# Bonds
# --------------------------------------------------------------------------- #

# Credit spread over the risk-free curve, and annualised default probability, by rating.
RATING_SPREAD: dict[str, tuple[float, float]] = {
    # rating: (spread, annual default prob)
    "AAA": (0.003, 0.0002),
    "AA":  (0.006, 0.0005),
    "A":   (0.010, 0.0010),
    "BBB": (0.018, 0.0030),
    "BB":  (0.035, 0.0120),
    "B":   (0.055, 0.0400),
    "CCC": (0.090, 0.1200),
}

# A plausible upward-sloping risk-free curve: maturity -> base yield.
RISK_FREE_CURVE: dict[float, float] = {
    1: 0.035, 2: 0.038, 3: 0.040, 5: 0.043,
    7: 0.046, 10: 0.048, 20: 0.052, 30: 0.055,
}

# Fictional corporate issuers per rating (clearly invented, not real companies).
CORP_ISSUERS: dict[str, str] = {
    "AAA": "Meridian Capital",
    "AA":  "Northbridge Industries",
    "A":   "Cascade Logistics",
    "BBB": "Harborline Foods",
    "BB":  "Vertex Drilling",
    "B":   "Ironwood Resorts",
    "CCC": "Pinnacle Aero",
}


def _bond_yield(base: float, spread: float, rng: random.Random) -> float:
    return round(clamp(base + spread + rng.gauss(0, 0.002), 0.005, 0.40), 4)


def build_bonds() -> list[dict]:
    bonds: list[dict] = []

    # Government ladder (AAA, full risk-free curve).
    for mat, base in RISK_FREE_CURVE.items():
        bid = f"GOVT-{int(mat)}Y"
        r = rng_for(bid, "bond")
        y = _bond_yield(base, 0.0, r)
        bonds.append(
            {
                "id": bid,
                "name": f"Government Treasury {int(mat)}Y",
                "issuer_type": "government",
                "rating": "AAA",
                "face_value": 1000.0,
                "coupon_rate": y,            # issued near par
                "maturity_years": float(mat),
                "base_yield": y,
                "default_prob": 0.0001,
            }
        )

    # Corporate bonds: each rating at 5Y and 10Y.
    for rating, (spread, dprob) in RATING_SPREAD.items():
        issuer = CORP_ISSUERS[rating]
        for mat in (5, 10):
            base = RISK_FREE_CURVE[mat]
            bid = f"CORP-{rating}-{mat}Y"
            r = rng_for(bid, "bond")
            y = _bond_yield(base, spread, r)
            bonds.append(
                {
                    "id": bid,
                    "name": f"{issuer} {rating} Note {mat}Y",
                    "issuer_type": "corporate",
                    "rating": rating,
                    "face_value": 1000.0,
                    "coupon_rate": y,
                    "maturity_years": float(mat),
                    "base_yield": y,
                    "default_prob": round(dprob, 4),
                }
            )
    return bonds


# --------------------------------------------------------------------------- #
# Crypto (hand-authored, fictional)
# --------------------------------------------------------------------------- #

# (symbol, name, archetype, fair_value, volatility, fundamental_strength, supply)
CRYPTO_DEFS = [
    ("BTR",  "Bitron",      "store-of-value", 45000.0,  0.65, 0.50, 19_500_000),
    ("GILD", "Gildcoin",    "store-of-value", 320.0,    0.70, 0.40, 60_000_000),
    ("ETA",  "Ethera",      "platform",       2800.0,   0.75, 0.45, 120_000_000),
    ("SLR",  "Solaris",     "platform",       95.0,     0.95, 0.35, 450_000_000),
    ("QNT",  "Quanta",      "platform",       55.0,     0.90, 0.35, 250_000_000),
    ("NMB",  "Nimbus",      "platform",       12.0,     1.00, 0.30, 1_200_000_000),
    ("VLTX", "VaultX",      "defi",           18.0,     1.05, 0.25, 800_000_000),
    ("LNR",  "Lunar",       "defi",           1.40,     1.40, 0.15, 2_000_000_000),
    ("BONE", "Dogebone",    "meme",           0.080,    1.30, 0.10, 140_000_000_000),
    ("FRG",  "Froggo",      "meme",           0.000012, 1.50, 0.05, 420_000_000_000),
    ("MEMZ", "Memez",       "meme",           0.0021,   1.45, 0.06, 90_000_000_000),
    ("SUSD", "StableUSD",   "stablecoin",     1.00,     0.02, 0.98, 80_000_000_000),
]


def build_crypto() -> list[dict]:
    out: list[dict] = []
    for sym, name, arch, fv, vol, strength, supply in CRYPTO_DEFS:
        out.append(
            {
                "symbol": sym,
                "name": name,
                "archetype": arch,
                "fair_value": fv,
                "volatility": vol,
                "fundamental_strength": strength,
                "circulating_supply": float(supply),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing {CSV_PATH}. Place the S&P 500 constituents CSV there.")

    stocks = build_stocks()
    bonds = build_bonds()
    crypto = build_crypto()

    write_json(SEED_DIR / "stocks.json", stocks)
    write_json(SEED_DIR / "bonds.json", bonds)
    write_json(SEED_DIR / "crypto.json", crypto)

    print(f"seed={SEED}")
    print(f"  stocks: {len(stocks):>4}  -> {SEED_DIR / 'stocks.json'}")
    print(f"  bonds:  {len(bonds):>4}  -> {SEED_DIR / 'bonds.json'}")
    print(f"  crypto: {len(crypto):>4}  -> {SEED_DIR / 'crypto.json'}")


if __name__ == "__main__":
    main()
