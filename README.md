# Trader "PRO"

A market-simulation game. Start with a pile of virtual cash and a universe of tradable
assets — stocks, bonds, crypto, and leverage — and grow (or blow up) your net worth by
trading against a living, seeded, occasionally-collapsing market.

The market isn't scripted. Prices come from a layered simulation that mixes slow
fundamental drift, random noise, sector correlations, a shifting greed/fear mood, and
discrete shocks — earnings, rate moves, and rare **black-swan crashes** that cascade into
margin-call liquidations. It's an open-ended sandbox: no win condition and no hard
game-over (run out of money and you can take a loan to claw back).

See **[`design.md`](design.md)** for the full design and **[`WORKLOG.md`](WORKLOG.md)** for
the build history.

## Status

**V1 — feature-complete local single-player.** Four asset classes, longs / shorts /
2:1 margin with margin calls, 8 market "personalities", a seeded event system with
black-swan cascades, loans, buyable price predictions, brokerage fees, save/load, and two
front-ends: a plain CLI and a live retro **TUI**. V2 (web) and V3 (multiplayer) are
designed but not built — see the roadmap in `design.md` §9.

## Quick start

The core game needs **Python 3.10+** and nothing else — the engine, CLI, and save/load use
only the standard library.

```bash
python play.py          # or:  python -m trader_pro
```

You'll pick a volatility profile (1–8), a world seed, starting cash, and a fee level, then
start trading.

### Live TUI (retro terminal client)

```bash
pip install "textual<0.72"      # see the version note below
python play_tui.py              # or:  python -m trader_pro.tui  (or: start.cmd)
```

The market **ticks live**. An amber ticker tape scrolls under the header; the board shows your
holdings plus a watchlist; the right column shows a net-worth sparkline, a **live price chart of the
highlighted asset**, your positions, and a scrolling news log.

| Key | Action |
|---|---|
| `Space` | play / pause |
| `[` / `]` | slower / faster |
| `s` / `h` / `d` | step 1 minute / 1 hour / 1 day |
| `0`–`4` | board view: 0 owned · 1 crypto · 2 stocks · 3 bonds · 4 watchlist |
| `5` | top movers — biggest 1D% gainers & losers across the market |
| `o` | sort the board by 1D % (toggle) |
| `c` | cycle the chart range (1H → 1D → 3D → 1W) |
| `Enter` | open the trade dialog for the highlighted asset |
| `:` | command line (every CLI command below works) |
| `Ctrl+N` | new world |
| `Ctrl+S` / `Ctrl+L` | save · load (the load browser lists slots with net worth, return, and age) |
| `?` | help · `q` quit (autosaves first) |

The game **autosaves** as you play and on quit; relaunching `play_tui.py` **resumes your last
game** automatically (press `Ctrl+N` for a fresh one). Saves live in `saves/<slot>.world` and are
written atomically (a crash mid-save can't corrupt a slot).

> **Textual version note.** The TUI is pinned to `textual>=0.50,<0.72`. Textual 0.72.0
> introduced a regression that deadlocks the trade-dialog teardown and freezes the whole
> app (Ctrl-C included); 0.71.0 is the last good release. Full bisect and evidence in
> [`docs/freeze-bug/README.md`](docs/freeze-bug/README.md). If you already have a newer
> Textual, downgrade with `pip install "textual<0.72"`.

## Commands

Both front-ends share the same command set (in the TUI, press `:` first):

```
market | m                overview: your holdings + the crypto board
stocks [n] | bonds | crypto [n]   list a kind
find <text>               search by name or symbol
look <SYM> | l            asset detail + a recent price sparkline
save [name] | load [name] persist / restore a slot   (load with no name opens the browser)
saves                     browse, load, or delete save slots
buy  <SYM> <qty|$amount>   e.g. 'buy AAPL 10'  or  'buy BTR $500'
sell <SYM> <qty|all>       e.g. 'sell AAPL 5'  or  'sell BTR all'
short <SYM> <qty|$amt>     open/extend a short (profit if it falls)
cover <SYM> [qty|all]      buy back a short
                           (buying uses up to 2:1 margin; leverage can trigger margin calls)
port | p                   portfolio, net worth & P&L
news                       recent market headlines
predict <SYM> [1d|6h]      buy a forecast (accuracy depends on the world's profile)
loan <amount>              borrow cash (no game-over); rate scales with leverage
repay [amount|all]         pay down loans (highest-rate first)
fees [off…diabolic]        brokerage difficulty — commission on every trade
step | hour | day          advance 1 min / 1 hour / 1 day
next <ticks>               advance N minutes
run <ticks> [delay]        live auto-advance
save [name] | load [name]  persist the world
quit
                           (1 tick = 1 simulated minute)
```

## How it works

The whole market is a **pure function of `(world_seed, tick)`**, evaluated through five
nested time layers — Era → Cycle → Session → Hour → Minute. Slow layers commit to seeded
anchors ahead of time; fast layers interpolate the path between them with noise. Two
consequences fall out of this:

- **Replayable.** Same seed → the same world, every time.
- **Cheap fast-forward.** To know a price three hours out, the engine evaluates the seeded
  anchors directly rather than grinding 180 individual minutes — so idle catch-up and
  "resume exactly where I left off" are the same operation.

The signature mechanic lives in the **Hour** layer: because the hour's close is decided in
advance, a stock can climb through the first half and still be set to dump into the close.
Reading that foreshadowing (the news, the shape of the move) is the skill.

**Market personalities.** Every world is created with one of 8 volatility profiles —
Calm · Steady · Normal- · Normal · Changing · Unstable · Volatile · Apocalyptic — that tune
baseline volatility, event frequency, crash-cascade severity, and how *predictable* the
world is (which caps prediction accuracy). Measured daily-return spread runs from ~2% on
Calm to ~6%+ on Apocalyptic before events, with fat tails from black swans on top.

**Drama.** A seeded, deterministic event schedule layers micro events (earnings, coin
pumps), macro events (sector rotations, rate moves), and rare **black swans** — market-wide
plunges that spawn a burst of correlated aftershocks over the following days. A large enough
drop can force margin-call liquidations, which push prices down further: that feedback loop
is what turns a dip into a crash. Bonds catch a flight-to-safety bid when equities tank.

## Project layout

```
trader_pro/                the Python package (engine, front-ends, save/load)
  core/
    models.py              seed-data record types + loader
    world.py               World / WorldConfig / MarketState — the live, serializable state
    engine.py              the layered tick engine (prices = f(seed, tick))
    profiles.py            the 8 market personalities + their coefficients
    portfolio.py           positions, cash, margin, loans, net-worth history
    orders.py              buy/sell/short/cover, margin checks, fees, forced liquidation
    events.py              seeded events, black swans & crash cascades
    predictions.py         buyable, seeded price forecasts
  cli.py                   the text front-end (TraderApp)
  tui.py                   the live Textual TUI
data/
  sp500_constituents.csv   raw S&P 500 list (source for stock seeds)
  seeds/                   generated starting universe — stocks.json, bonds.json, crypto.json
scripts/
  build_seed.py            regenerates the seed files (deterministic)
  validate_engine.py, compare_profiles.py, cascade_demo.py, …   headless validation & charts
tests/                     ~50 tests across 12 files
docs/freeze-bug/           the Textual-regression investigation
saves/                     runtime world saves (gitignored)
```

## Seed data

The starting universe is built once from a public S&P 500 constituents CSV plus generated
bonds and a handful of fictional crypto coins:

```bash
python scripts/build_seed.py
```

The generator is **deterministic** (fixed seed), so the universe is byte-reproducible.
Seed accuracy is deliberately ballpark — stock prices and caps are plausible draws, not real
figures, and crypto names are invented to keep it clearly a game. The interesting behaviour
comes from the simulation, not the seed.

## Tests

```bash
python -m pytest          # ~50 tests across 12 files
```

Covers seed determinism, the world model, orders, margin/short behaviour, the event system,
loans, predictions, profiles, and the CLI/TUI. The two trade-dialog freeze tests are
version-gated: they pass on `textual<0.72` and `xfail` on newer releases, so an unexpected
pass will flag that the upstream regression is fixed and the cap can be lifted.

## Requirements

- **Core game:** Python 3.10+, standard library only.
- **TUI:** `textual>=0.50,<0.72`.
- **Dev/validation charts:** `matplotlib` (and `cairosvg` only to rasterise TUI
  screenshots).

See [`requirements.txt`](requirements.txt) — the optional extras are commented there.

## License

No license file yet — all rights reserved by default until one is added.
