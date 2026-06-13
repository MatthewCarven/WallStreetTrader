"""Market personalities — the 8-point volatility scale (design.md §4.5).

A *profile* is a named bundle of parameters that gives a whole world its character, from
glassy-calm to apocalyptic. It is the single source of truth for the scale: the engine
reads it for volatility, the (future) event & cascade systems read it for drama, and the
(future) prediction economy reads `predictability` for how accurate a bought peek can be.

Canonical order (level 1..8):
    Calm · Steady · Normal- · Normal · Changing · Unstable · Volatile · Apocalyptic
with **Normal** as the anchored baseline (every *_mult == 1.0 there).

This module imports nothing else from the package, so both `world` and `engine` can depend
on it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """One market personality. The `*_mult` fields are multipliers on the Normal baseline."""

    name: str
    level: int            # 1..8 on the scale
    tagline: str          # short description of the feel

    # --- consumed now (V0.3 engine) ---
    vol_mult: float       # scales idiosyncratic + factor price noise
    sentiment_mult: float # scales the swing of the global risk mood
    rate_mult: float      # scales how far interest rates roam

    # --- forward-looking knobs (read by later systems) ---
    event_rate_mult: float  # frequency of discrete events       (V1.4 drama)
    cascade_mult: float     # crash contagion / selloff severity (V1.4 drama)
    predictability: float   # 0..1 — ceiling on bought-prediction accuracy (V1.5, §5.4)

    def describe(self) -> str:
        return (
            f"[{self.level}] {self.name:<11} — {self.tagline}\n"
            f"      vol×{self.vol_mult:<4}  sentiment×{self.sentiment_mult:<4}  "
            f"rate×{self.rate_mult:<4}\n"
            f"      events×{self.event_rate_mult:<4}  cascades×{self.cascade_mult:<4}  "
            f"predictability={self.predictability:.2f}"
        )


# The locked scale. Numbers are tuned so every ladder is monotonic and Normal == 1.0.
PROFILES: tuple[MarketProfile, ...] = (
    MarketProfile("Calm",        1, "Glassy. Slow drift, rare events, shallow dips. Pure idle.",
                  vol_mult=0.35, sentiment_mult=0.40, rate_mult=0.40,
                  event_rate_mult=0.30, cascade_mult=0.20, predictability=0.92),
    MarketProfile("Steady",      2, "Gentle trends, the occasional wobble.",
                  vol_mult=0.60, sentiment_mult=0.65, rate_mult=0.60,
                  event_rate_mult=0.55, cascade_mult=0.45, predictability=0.82),
    MarketProfile("Normal-",     3, "A touch tamer than baseline — forgiving but alive.",
                  vol_mult=0.85, sentiment_mult=0.85, rate_mult=0.85,
                  event_rate_mult=0.80, cascade_mult=0.75, predictability=0.72),
    MarketProfile("Normal",      4, "The baseline — believable markets, real but survivable crashes.",
                  vol_mult=1.00, sentiment_mult=1.00, rate_mult=1.00,
                  event_rate_mult=1.00, cascade_mult=1.00, predictability=0.62),
    MarketProfile("Changing",    5, "Frequent rotations, livelier swings.",
                  vol_mult=1.30, sentiment_mult=1.20, rate_mult=1.20,
                  event_rate_mult=1.35, cascade_mult=1.40, predictability=0.50),
    MarketProfile("Unstable",    6, "Sharp moves, regular scares, fat tails.",
                  vol_mult=1.70, sentiment_mult=1.50, rate_mult=1.45,
                  event_rate_mult=1.80, cascade_mult=1.90, predictability=0.38),
    MarketProfile("Volatile",    7, "Wild. Big profits and epic fails on tap.",
                  vol_mult=2.30, sentiment_mult=1.90, rate_mult=1.75,
                  event_rate_mult=2.50, cascade_mult=2.60, predictability=0.26),
    MarketProfile("Apocalyptic", 8, "Maximum chaos — frequent black swans, brutal cascades.",
                  vol_mult=3.20, sentiment_mult=2.50, rate_mult=2.20,
                  event_rate_mult=3.50, cascade_mult=3.80, predictability=0.14),
)

PROFILE_BY_NAME: dict[str, MarketProfile] = {p.name: p for p in PROFILES}
PROFILE_NAMES: tuple[str, ...] = tuple(p.name for p in PROFILES)
DEFAULT_PROFILE = "Normal"


def get_profile(name: str) -> MarketProfile:
    try:
        return PROFILE_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown profile {name!r}; choose from {PROFILE_NAMES}") from None


def prediction_accuracy(profile_name: str) -> float:
    """Ceiling on how accurate a bought prediction can be in this world (§5.4)."""
    return get_profile(profile_name).predictability
