# Trader "PRO" — Design Document

> Status: **Working draft v0.3** — a living doc. Decisions are locked unless marked 🟡.
> Last updated: 2026-06-14

---

## 1. Vision

Trader Pro is a market-simulation game. You start with a pile of virtual cash and a
universe of tradable assets — stocks, bonds, crypto, and leveraged/derivative
products — and you grow (or blow up) your net worth by trading against a living,
breathing simulated market.

The market is **not** scripted. Prices move from an underlying simulation that mixes
slow fundamental drift with random noise, sector correlations, occasional shocks, and
the ever-present possibility of a bubble, a panic, or a full-blown crash. There is no
"correct" answer to beat — it's an **open-ended sandbox** where the fun comes from
reading the market, managing risk, and surviving (or profiting from) chaos.

### Design north star: idle-friendly, low-maintenance play
The market should be enjoyable to dip into for two minutes or to watch tick over a long
session. Changes are mostly **small and gradual** so a player can leave, come back
later, and find the world plausibly evolved rather than reset. This "idle" quality is a
first-class design constraint — it shapes the layered time model (§5), the volatility
profiles (§4.5), and the persistence model (§7).

---

## 2. Design pillars

1. **A market that feels alive.** Prices drift, react, and occasionally break.
   Believable enough to reward intuition, random enough that no strategy is a sure thing.
2. **Idle-respecting.** Step away and the world keeps a slow, sensible pace. Coming back
   should feel like checking in, not catching up on homework.
3. **Risk is the whole game.** Bonds are boring-safe; crypto and leverage can 10x or
   zero you. The spread between them *is* the gameplay.
4. **Sandbox, not a score-chase.** No forced win condition and no hard "game over" — if
   you blow up you can take a loan and claw back (§8.2). The player decides what
   "winning" means.
5. **Build once, grow outward.** The simulation core is platform-agnostic so the same
   engine runs locally today, behind a web client tomorrow, and on a shared multiplayer
   server later — without a rewrite (§6).

---

## 3. Asset classes (v1 scope: all four)

Accuracy of seed data is explicitly **not critical** — ballpark figures are fine. The
real behaviour comes from the simulation, not from the seed.

| Class | Feel | Key drivers | Risk |
|---|---|---|---|
| **Stocks** | The core market | Company "fundamentals" + sector trend + market sentiment | Medium |
| **Bonds** | Safe yield / ballast | Interest-rate level, issuer credit rating | Low (rate-sensitive) |
| **Crypto** | Casino wing | Hype cycles, high noise, weak fundamentals | Very high |
| **Derivatives / leverage** | Risk amplifier | Margin, shorting, options on the above | Extreme |

### 3.1 Stocks
Seeded from a public **S&P 500 / large-cap CSV** (name, ticker, sector, rough market
cap). Each stock carries hidden **fundamentals** (a fair-value anchor and a growth rate)
that the price drifts toward over time, plus sector membership so correlated names move
together.

### 3.2 Bonds
Modeled simply: a face value, a coupon (yield), a maturity, and an issuer credit rating.
Price moves **inversely** to a global interest-rate variable. Government bonds = near
risk-free anchor; corporate/junk bonds = higher yield, real default risk during crashes.
Bonds are the player's "park cash safely" option and a natural hedge.

### 3.3 Crypto
A handful of fictional coins with **weak fundamental anchors** and **high noise**. Prone
to pumps, manias, and brutal drawdowns. This is where the wild upside and the rug-pulls
live.

### 3.4 Derivatives & leverage
Layered on top of the spot assets:
- **Margin / leverage** — borrow to amplify a position; margin calls force liquidation
  if equity drops too far.
- **Short selling** — profit when an asset falls (and get squeezed when it rips).
- **Options** — calls/puts for asymmetric bets. **Deferred:** implemented only if the
  spot + margin + short core makes them clean to add; otherwise the first post-v1
  expansion.

---

## 4. The simulation engine (heart of the game)

Each asset's price comes from two combined ideas: a set of **forces** that decide how a
single move is shaped (§4.1), evaluated within a stack of **time layers** that decide how
those moves are organised across horizons (§5). Read §4 and §5 together — they're the two
axes of the same engine.

### 4.1 Price forces (per asset, per move)
A practical blend rather than a single clean equation:

```
Δprice =  drift_toward_fundamental      // slow pull to fair value
        + sector_trend                  // shared move across a sector/class
        + market_sentiment              // global risk-on / risk-off mood
        + random_noise                  // per-asset volatility (GBM-style)
        + event_impact                  // shocks from the event system (§4.4)
        + momentum_feedback             // crowd-following; fuels bubbles & panics
```

- **Geometric Brownian Motion** as the noise backbone (returns, not absolute prices, so
  cheap and expensive assets behave proportionally).
- Each asset has a **volatility** parameter: bonds low, blue-chip stocks medium, crypto
  high. This single knob does most of the per-asset "feel" tuning.
- **Mean reversion** keeps prices tethered to fundamentals so the world doesn't drift to
  nonsense over long idle periods.

### 4.2 Correlations
Assets aren't independent. The **sentiment** variable nudges the whole market; **sector**
and **class** factors nudge groups. This is what makes a "tech selloff" or "flight to
bonds" emerge naturally instead of being hard-coded.

### 4.3 Sentiment / market regime
A slow-moving global mood drifting between "greed" and "fear." It biases drift and
volatility market-wide and is the mechanism behind broad bull markets, bear markets,
bubbles, and panics. (In layer terms it lives in the Era/Cycle layers — §5.)

### 4.4 Events & shocks (the drama)
A scheduler injects discrete events on top of the continuous model:

- **Micro (common, small):** earnings beats/misses, analyst notes, minor coin pumps.
  Tiny nudges that keep idle play gently interesting.
- **Macro (rarer, bigger):** rate hikes/cuts, sector booms, regulatory news.
- **Black-swan (rare, severe):** flash crash, crypto exchange collapse, credit crisis,
  mass selloff cascade.

**Cascade / contagion mechanic:** a large enough drop raises a "panic" level that
increases the *probability and size of further drops* — and can trigger margin-call
liquidations, which themselves push prices down (a feedback loop). This is what turns a
dip into a **crash**. Symmetrically, euphoria can inflate a **bubble** that eventually
pops. How violent this gets by default is set by the world's volatility profile (§4.5).

### 4.5 Volatility profiles ("market personality")
Every world is created with a player-chosen profile on an **8-point scale**. It tunes
baseline volatility, event frequency, and crash-cascade severity together — so casual
idlers and adrenaline-seekers each get a good experience from the same engine. The same
profile also sets how *predictable* the world is, which feeds prediction accuracy (§5.4):

| | Profile | Feel |
|---|---|---|
| 1 | **Calm** | Glassy. Slow drift, rare events, shallow dips. Pure idle. |
| 2 | **Steady** | Gentle trends, occasional wobble. |
| 3 | **Normal-** | A touch tamer than baseline — forgiving but alive. |
| 4 | **Normal** | The baseline — believable markets, real but survivable crashes. |
| 5 | **Changing** | Frequent rotations, livelier swings. |
| 6 | **Unstable** | Sharp moves, regular scares, fat tails. |
| 7 | **Volatile** | Wild. Big profits and epic fails on tap. |
| 8 | **Apocalyptic** | Maximum chaos — frequent black swans, brutal cascades. |

> Canonical 8 levels: **Calm · Steady · Normal- · Normal · Changing · Unstable ·
> Volatile · Apocalyptic**, with **Normal** as the anchored baseline.

All of §4 is **parameters in a config**, never magic numbers in code. A profile is just a
named bundle of those parameters — the foundation of the **Profiles** milestone (V0.5).

**Locked coefficients (V0.5)** — multipliers on the *Normal* baseline (all 1.0 there).
`predictability` (0–1) is the ceiling on bought-prediction accuracy (§5.4); it falls as
chaos rises. Implemented in `trader_pro/core/profiles.py`.

| # | Profile | vol× | sentiment× | rate× | events× | cascades× | predictability |
|---|---|---|---|---|---|---|---|
| 1 | Calm | 0.35 | 0.40 | 0.40 | 0.30 | 0.20 | 0.92 |
| 2 | Steady | 0.60 | 0.65 | 0.60 | 0.55 | 0.45 | 0.82 |
| 3 | Normal- | 0.85 | 0.85 | 0.85 | 0.80 | 0.75 | 0.72 |
| 4 | Normal | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.62 |
| 5 | Changing | 1.30 | 1.20 | 1.20 | 1.35 | 1.40 | 0.50 |
| 6 | Unstable | 1.70 | 1.50 | 1.45 | 1.80 | 1.90 | 0.38 |
| 7 | Volatile | 2.30 | 1.90 | 1.75 | 2.50 | 2.60 | 0.26 |
| 8 | Apocalyptic | 3.20 | 2.50 | 2.20 | 3.50 | 3.80 | 0.14 |

The `vol`/`sentiment`/`rate` knobs are live in the V0.3 engine; `events`/`cascades` are
read by the drama systems (V1.4) and `predictability` by the prediction economy (V1.5).
Measured effect on a stock's daily-return std: Calm ≈2.2% → Normal ≈3.1% → Volatile ≈5.1%
→ Apocalyptic ≈6.5% (monotonic).

---

## 5. Time model — layered & seeded

The player wanted minute-by-minute action in the short term, but a longer term that is
**pre-committed** — so an asset can drift green early in the hour yet be destined to tank
into the close. We get this from a stack of **nested time layers**: slower layers commit
to seeded **anchors/targets** ahead of time; faster layers fill in the path between them
with noise.

### 5.1 The five layers
| Layer | Horizon | What it commits to |
|---|---|---|
| **Era** | months–years | Secular regime: bull/bear epoch, rate environment, baseline sentiment. Barely moves. |
| **Cycle** | days–weeks | Sector rotations and medium swings ("tech is hot this fortnight"). |
| **Session** | a day | The day's directional bias and a seeded target close. |
| **Hour** | an hour | A pre-committed hour: open, seeded **target close**, and intra-hour shape. |
| **Minute** | the tick | Live noise interpolating toward the hour's committed close. 1 tick = 1 sim-minute. |

**The signature mechanic lives in the Hour layer:** because the hour's endpoint is
decided in advance, a stock can climb through the first half and still be set to dump
into the close. Skilled players read the foreshadowing (news, the shape of the move) and
exit in time; naïve players get caught.

### 5.2 Seeded, replayable, and cheap to fast-forward
The slow layers are **seeded functions of the tick index**, which gives us three things:

- **Replayability** — same world seed → same Era/Cycle/Session/Hour anchors → the same
  world, every time.
- **Cheap fast-forward** — to know the price three hours out we *evaluate the seeded
  anchors directly*; we only generate minute-detail for the window actually being viewed.
  No grinding 180 individual minutes. This is what makes idle catch-up effectively free
  (§7).
- **World forks** — a world seed *is* a market fork. Same seed = a world anyone can
  replay; a regional/"local" fork is just a different seed (or a shared seed with local
  deviations) — see §6.4.

### 5.3 Baseline vs. deviations (single-player ↔ multiplayer)
A tension worth naming: fully pre-determined hours are perfect for seeded/replayable
worlds and idle, but in V3 multiplayer **player trades must move price**, so the future
can't be 100% locked. Resolution:

> The seeded layers define each asset's **natural baseline trajectory**. Events and
> (in V3) aggregate **order-flow** apply **deviations on top**.

Single-player V1 stays near-deterministic and replayable (deviations minimal). V3 lets
the crowd meaningfully bend the path. Same engine, one knob.

### 5.4 Hidden future + buyable predictions
The committed future is **hidden by default** — skill is reading the foreshadowing. On
top of that, players can **buy "predictions"**: probabilistic peeks at upcoming seeded
anchors, creating a risk/info economy. They're hints, not guarantees, and deviations
(§5.3) can still bend the outcome.

**Accuracy is capped by the world's volatility profile (§4.5).** A *Calm* world is
genuinely foreseeable, so predictions there are sharp; an *Apocalyptic* one is barely
knowable, so even an expensive prediction is a fuzzy lean. This reuses the profile knob
and makes calmer worlds feel "readable" and chaotic ones feel like gambling — by design.

**Tiers (broad & cheap → specific & dear):**
- **Market trend** — overall risk-on/risk-off direction. Cheap, low-resolution.
- **Sector trend** — where a sector/class is heading. Mid.
- **Single-asset peek** — an asset's likely hour-close. Priciest, most actionable.

**Cost scales with information *scarcity*, mirroring real coverage asymmetry.** Large,
heavily-"covered" companies are cheaper and more reliable to predict; small/obscure names
and crypto cost more and carry more uncertainty — but offer a bigger edge to whoever pays
to dig. So a peek at a mega-cap is cheap and dependable; a peek at a tiny coin is dear and
hazier, but the payoff if you're right is larger.

> 🟡 Exact pricing curve, refresh rate, and how strongly accuracy degrades across the
> 8 profiles are tuning items (§10).

### 5.5 Speed control
Wall-clock → sim-time mapping is player-set: **Paused** (plan calmly) · **Slow**
(idle drip) · **Fast-forward** (burn through sim-days) · **Step** (advance exactly one
tick/day — the turn-based mode). One dial delivers both the real-time and turn-based
experiences; they're the same loop at different speeds.

### 5.6 Core loop
```
observe market  →  form a view  →  place orders (buy/sell/short/leverage)
      →  advance time (at chosen speed)  →  see P&L & news  →  repeat
```

---

## 6. Architecture — "build once, grow outward"

We **decouple the simulation from presentation and platform** so the engine is never
rewritten as we scale up. Language: **Python** (clean for the simulation math, the V0/V1
local game, and the V3 authoritative server).

```
┌─────────────────────────────────────────────┐
│  SIMULATION CORE  (pure Python, seedable)    │
│  • assets, prices, portfolios, orders        │
│  • layered tick engine, events, P&L          │
│  • NO UI, NO networking                       │
└───────────────┬─────────────────────────────┘
                │  stable API (advance tick, place order, get state)
   ┌────────────┼───────────────────────────────┐
   │            │                                │
┌──▼──────┐ ┌───▼─────────┐ ┌────────────────────▼─┐
│ V1 LOCAL│ │ V2 WEB      │ │ V3 MULTIPLAYER SERVER │
│ desktop │ │ web client  │ │ shared market, accts, │
│ single  │ │ + server-   │ │ authoritative server, │
│ player  │ │ side sim    │ │ order-flow moves price│
└─────────┘ └─────────────┘ └───────────────────────┘
```

### 6.1 The simulation core
A self-contained Python package with a **clean API** and no UI/network dependencies. It
takes a state + advances a tick and produces the next state. Key properties:

- **Seedable** — every world is reproducible from its seed (powers replays and forks).
- **Serializable state** — a whole game saves/loads/ships as one blob, unchanged. This is
  what makes local → server migration cheap: the server runs the same core,
  authoritatively.
- **Deterministic given (state, seed, inputs)** — essential for V3, where all clients must
  agree on prices.

### 6.2 Python's implication for V2 web
Python runs the V0/V1 local game and the V3 server directly, but it **won't run
client-side in the browser**. So **V2 is a thin web client over a server-side
simulation** (the core runs on a server; the browser just renders and sends orders) —
rather than a client-side sim. This is fine and actually moves us most of the way toward
V3's server architecture.

### 6.3 Evolution path
- **V0 — Scaffolding.** Seed data, core data model, the bones of the engine. No real game
  yet.
- **V1 — Local single-player.** Core + simple UI on one machine. Validates the *feel*.
- **V2 — Web.** Same core, server-side, behind a browser client. Shareable, broader reach.
- **V3 — Multiplayer server.** Authoritative shared market; **player order-flow moves
  prices**, enabling real player-driven selloffs. Accounts, leaderboards, persistence.

### 6.4 World forks / "local" markets
Because a world is fully defined by its seed + profile + config, spinning up a **regional
or "local" market** is just creating a world from a different seed (point: everyone lives
somewhere unique — let communities run their own fork). Forks can be fully independent or
share a base seed with local deviations layered on (§5.3).

---

## 7. Data & persistence

### 7.1 Seed database
A one-time scrape builds the starting universe:
- **Stocks:** from a public **S&P 500 / large-cap CSV** — name, ticker, sector, rough
  market cap → mapped to a fair-value anchor + growth rate + volatility.
- **Bonds:** a generated set across issuers, ratings, coupons, maturities.
- **Crypto:** a small hand-authored set of fictional coins.

Stored as static seed files (JSON/CSV) loaded at world creation. The immutable seed is
kept separate from the live, changing state (prices, sentiment, portfolios).

### 7.2 Save state & the canonical clock
The canonical clock is the **tick index**, stored in the save blob alongside the world
seed and RNG position. Because the slow layers are seeded functions of that index,
**"resume exactly" and "fast-forward" are the same operation** — set the tick index to
where you want and evaluate the anchors there. No minute-by-minute replay needed.

**Frozen-resume is *the* model.** The world advances only while the game is actually
running — it's happy to **live in the taskbar and keep ticking while open**, but the
moment it's closed it freezes. Reopen (or restart the server after a crash) and it
continues **bit-for-bit from the last tick**. Real-world elapsed time is irrelevant: a
world you closed for a month resumes exactly where you left it. This is the robust,
fully-deterministic default for everything up to and including the authoritative server.

*(Living-world — advancing to match wall-clock on load — stays in our back pocket as a
possible per-world toggle if we ever want an idle-MMO variant, but it's **not** part of
the baseline design. The architecture already supports it for free since catch-up and
exact-resume are the same operation.)*

### 7.3 Storage by platform
- **V1:** a local save file (serialized core state).
- **V2:** same blob in a lightweight backend.
- **V3:** authoritative state in a server DB — market state global per world; portfolios
  per account.

Designing the core's state as one serializable object means "save game" and "sync to
server" are the same operation at heart.

---

## 8. Player experience

### 8.1 UI surface (v1 minimum)
- **Market view** — assets, current price, change, a sparkline.
- **Asset detail** — price chart, fundamentals (stocks), recent news/events.
- **Trade panel** — buy / sell / short / set leverage; order confirmation.
- **Portfolio** — holdings, cash, net worth, P&L, margin health.
- **News / event feed** — the running story of the market.
- **Time control** — pause / speed / step.
- **Predictions** — buy a partial peek at an upcoming anchor (§5.4).

### 8.2 No game-over — loans instead
Players start with **$2,500** in cash. Blowing up doesn't end the game: a player who runs
out (or gets margin-liquidated) can **apply for a loan** — cash now, repaid with interest,
with the risk of a debt spiral if they keep losing. This preserves the open-ended sandbox
while still making ruin *feel* like ruin.

**Interest scales with leverage, not raw loan size.** The driver is the loan relative to
the player's collateral (net worth) — which is both realistic and the right risk signal:

- A **small loan against solid assets** is cheap (well-collateralised, low lender risk).
- A **large loan relative to net worth** is progressively more expensive — and past a
  high leverage ratio, lenders charge punitive rates or refuse outright.

So a modest top-up is affordable; trying to borrow your way out of a deep hole is brutally
costly, exactly as it should be. (This resolves the "reversed" instinct: it's not absolute
dollars but *how leveraged the loan makes you* that sets the rate — mega-loans backed by a
mega-portfolio stay cheap, mortgage-style.)

> 🟡 Exact tiers, base rate, per-tick compounding, and the borrowing-limit ceiling are
> tuning items (§10).

### 8.3 Optional sandbox flavour
Self-set goals, personal stats ("biggest single-day gain", "survived N crashes"), and
milestone badges — engagement without forcing a win condition.

---

## 9. Roadmap (granular)

The headline path is **V0 → V1 → V2 → V3**; sub-steps below keep each phase shippable.

**V0 — Scaffolding & core bones**
- **V0.1** Project setup; seed scrape (S&P 500 CSV → stocks); seed files for bonds/crypto.
- **V0.2** Core data model: assets, portfolio, orders; serializable world state + seed.
- **V0.3** Layered tick engine (Era→Minute) with seeded anchors; price forces (§4.1).
- **V0.4** Headless validation: chart seeded runs, confirm the "green-then-tank hour" and
  mean-reversion behave. *Feel is won or lost here.*
- **V0.5** **Profiles** — the 7-point volatility scale (§4.5) + market-personality config.

**V1 — Local single-player**
- **V1.1** Portfolio + orders (buy/sell); minimal UI; save/load (frozen-resume).
- **V1.2** Stocks + bonds fully playable; speed control (pause/slow/fast/step).
- **V1.3** Crypto; margin + short selling.
- **V1.4** Drama: crash cascades, bubbles, black-swan events, margin calls.
- **V1.5** Loans (§8.2); buyable predictions (§5.4).

**V2 — Web**
- **V2.1** Core behind a server API; thin browser client renders market + trades.
- **V2.2** Backend persistence; share-a-seed.

**V3 — Multiplayer**
- **V3.1** Accounts; authoritative shared market per world.
- **V3.2** Order-flow moves price (player-driven selloffs); leaderboards.
- **V3.3** World forks / regional "local" markets (§6.4).

*(Options, §3.4, slot in whenever the spot+margin core makes them clean — likely a V1.x
or post-V1 expansion.)*

---

## 10. Remaining open questions 🟡 (all tuning, none block V0)

1. ~~**Loan tiers**~~ ✅ Implemented in V1.5: APR by leverage ratio (≤0.25→6%, ≤0.75→12%,
   ≤1.5→22%, else 35%), per-minute compounding, borrow limit ≈2× net worth (with a $1,000
   hardship floor so you can always get back in). Starting cash **$2,500**. (`portfolio.py`)
2. ~~**Prediction economy**~~ ✅ Implemented in V1.5: cost = base × obscurity (mega-cap cheap,
   small-cap & crypto dear) × horizon; forecast noise = (1−predictability)·√horizon, so
   accuracy degrades Calm→Apocalyptic. (`predictions.py`, §5.4)
3. ~~**Profile coefficients** — the numbers behind the 8 levels.~~ ✅ Locked in V0.5
   (table in §4.5; `trader_pro/core/profiles.py`).

---

## 11. The V1.8 polish pass 🧽

Agreed 2026-08-04. Fifteen slices in four waves, each shippable + tested on its own (the
L1–L5 idiom from stop/limit orders). Options (§3.4, O1–O5) stays queued behind the pass.
Sizes: **S** = an evening slice, **M** = a full session.

**Wave A — session memory** *(foundations first: P5, P6, P12 and P14 all want settings keys)*

- [ ] **P1 · Settings expansion + session restore** (M) — generic get/set in `gui/settings.py`;
  persist & restore window geometry, board view + sort, chart range, speed. Fee level is
  deliberately excluded — it lives in `world.config` and travels with the save, not the install.
- [ ] **P2 · Live accent repaint** (M) — route the palette through a mutable theme object so the
  picker applies instantly; retires "restart to apply". Unlocks P14.
- [ ] **P3 · Autosave generations** (S) — rotate `autosave` → `.1` → `.2`; a corrupt newest
  falls back down the chain at resume.

**Wave B — feel** *(GUI-first; the TUI gets the terminal bell where it's a one-liner)*

- [ ] **P4 · Price-flash on the board** (S) — cells pulse P&L-green/red on tick moves, then fade.
  Respects the accent-vs-semantics split (§ the V1.7+ theming work).
- [ ] **P5 · Sound** (M) — retro chirps: fill, cancel, margin-call klaxon, black-swan stinger.
  Appearance ▸ Sound toggle persisted via P1. **Matthew: drop in PySynthRack for the synthesis.**
- [ ] **P6 · Tray + toasts** (M) — minimise-to-tray option; Windows toasts for fills / margin
  calls / black swans while hidden. The idle-friendly north star (§1), delivered.

**Wave C — trader QoL** *(engine + all three front-ends, exactly like the L slices)*

- [ ] **P7 · Blotter core** (M) — record every fill (manual, triggered, liquidation) on the
  portfolio: tick, side, qty, price, fee, realized P&L. Serialized with saves, back-compat.
- [ ] **P8 · Blotter UI** (M) — CLI `history`, a TUI screen, a GUI dialog + CSV export.
- [ ] **P9 · Stats + market-close recap** (M) — lifetime fees / interest / realized P&L, biggest
  win & loss, max drawdown; a recap line in all three feeds at each sim-day close.
- [ ] **P10 · Price alerts** (S/M) — notify-only resting kind; `is_triggered` does the hard part.
- [ ] **P11 · Trailing stops** (M) — TRAIL kind with a high-water-mark trigger, folded into the
  existing trade dialogs.
- [ ] **P12 · Editable watchlist** (S/M) — `watch` / `unwatch` commands + right-click add; saved
  with the world.

**Wave D — charts & branding**

- [ ] **P13 · Chart candy** (M) — crosshair + hover readout, ▲/▼ markers at your fills,
  cost-basis line, event diamonds where the black swan hit.
- [ ] **P14 · Theme presets + CRT scanlines** (S/M) — Phosphor / Amber / Ice / Paper presets on
  top of P2; the scanline overlay is the stretch goodie.
- [ ] **P15 · Icon, About, exe diet** (M) — programmatically drawn candlestick icon, About dialog
  with version, PyInstaller excludes to shrink the ~105 MB one-file exe.

**Unplanned, shipped on sight**

- [x] **P16 · TUI new-world picker** (S) — difficulty and fees were free-text `Input`s in the
  Ctrl+N modal, and the eight profile names weren't even listed; a typo silently kept your old
  profile, so you'd start a world you didn't ask for. Both are now `Select` dropdowns (short
  `4. Normal` labels, the selected profile's tagline live underneath), matching the GUI. Enter
  still starts from any field — a `NewWorldSelect` subclass rebinds only `enter`, leaving
  `↑ ↓ / Space` to open the list.

- [x] **P17 · Coalesced manual stepping** (S) — `s`/`h`/`d` advanced *and fully redrew the board*
  once per key event, so the terminal's key-repeat rate decided how much work the app did (~33 ms
  a press); holding a key queued work faster than it could drain. Now a leading-edge rate limit:
  the first press applies instantly, repeats inside a 50 ms window batch into one advance + one
  redraw. Leans on §5.2 — prices are pure in (seed, tick), so `_advance(n)` costs what
  `_advance(1)` does. Measured 52× less work on a 100-press burst.

**Dependencies:** P1 → {P5, P6, P12, P14} · P2 → P14 · P7 → {P8, P9}. Everything else can jump
the queue. If the pass drags, cut P11 and the scanlines first. **Parked:** achievements (becomes
P18 on request) and candlestick charts (a feature, not polish — needs OHLC aggregation).

---

*Next step: work the pass roughly A → B → C → D, then options (O1–O5).*
