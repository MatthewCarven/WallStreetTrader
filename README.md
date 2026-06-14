# Trader "PRO"

A market-simulation game: trade virtual stocks, bonds, crypto, and leveraged products
against a living, seeded, occasionally-collapsing market. Open-ended sandbox, idle-friendly.

See [`design.md`](design.md) for the full design.

## Status

**V0.1 — scaffolding & seed data.** The simulation engine itself comes in V0.2–V0.3.

## Layout

```
trader_pro/            # the Python package (the future simulation core lives here)
  core/
    models.py          # seed-data record types + loader
data/
  sp500_constituents.csv   # raw S&P 500 list (source for stock seeds)
  seeds/                   # generated seed files (the starting universe)
    stocks.json
    bonds.json
    crypto.json
scripts/
  build_seed.py        # regenerates the seed files (deterministic)
tests/
```

## Regenerating the seed data

```bash
python scripts/build_seed.py
```

The generator is **deterministic** (fixed seed), so the starting universe is reproducible.
Accuracy of the seed is deliberately ballpark — the interesting behaviour comes from the
simulation, not the seed (see design.md §3, §7.1).

## How to play (V1.1)

```bash
python play.py        # or:  python -m trader_pro
```

Pick a volatility profile and a world seed, then trade. Key commands:

- `market` — your holdings + the crypto board
- `stocks 15` / `bonds` / `crypto` — browse a kind
- `find tech` — search by name or symbol
- `look BTR` — asset detail + a recent price sparkline
- `buy AAPL 10` / `buy BTR $500` — buy by quantity or by dollar amount
- `sell BTR all` — sell a holding
- `port` — portfolio and P&L
- `short SLR 50` / `cover SLR all` — short selling (buying uses up to 2:1 margin)
- `predict BTR 1d` — buy a forecast (accuracy depends on the world's profile)
- `loan 1500` / `repay all` — borrow to recover (no game-over); rate scales with size
- `news` — recent market headlines (earnings, crashes, black swans)
- `step` / `hour` / `day` / `next 90` — advance simulated time (1 tick = 1 minute)
- `run 120` — live auto-advance
- `save` / `load` — persist the world

Saves live in `saves/` (gitignored).

## Requirements

Python 3.10+. Seed generation uses only the standard library. The engine (V0.2+) will add
`numpy` — see `requirements.txt`.
