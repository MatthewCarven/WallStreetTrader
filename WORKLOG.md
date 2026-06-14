# Trader PRO — Worklog

## 2026-06-14 — V0.1 scaffolding & seed data ✅

- Stood up the Python package layout (`trader_pro/`, `scripts/`, `tests/`, `data/`).
- Pulled the live **S&P 500 constituents** list (503 companies) → `data/sp500_constituents.csv`.
- Wrote `scripts/build_seed.py` (deterministic, seed=20260614) generating:
  - `stocks.json` — 503 equities with sector-tuned fair value, growth, volatility, market cap.
  - `bonds.json` — 22 bonds: an 8-point government risk-free ladder + corporate notes
    across AAA→CCC (yield and default risk rise as rating falls).
  - `crypto.json` — 12 fictional coins (store-of-value, platform, defi, meme, stablecoin).
- Added `trader_pro/core/models.py` — frozen seed records + `load_seed_universe()` loader.
- Tests in `tests/test_seed.py` all pass; rebuild is byte-identical (determinism confirmed).

**Decisions/notes**
- Seed accuracy intentionally ballpark (design.md §7.1). Stock prices/caps are plausible
  random draws, not real figures.
- Crypto names are invented to keep it clearly a game.

**Handoff / for Matthew**
- Not a git repo yet. Per our working agreement, `git init` is yours to run — say the word
  and I'll prep the first commit message and structure.

**Next (V0.2)**
- Core world model: live prices, portfolio, orders; serializable world state + seed.

## 2026-06-14 — V0.2 live world model ✅

- `world.py`: `World` + `WorldConfig` + `MarketState`. Unified asset registry
  (`STOCK:` / `BOND:` / `CRYPTO:` ids) over the seed universe; current prices, global
  interest rate & sentiment, tick clock. 537 tradable assets.
- `portfolio.py`: `Portfolio` / `Position` — cash, holdings, realized P&L, valuation
  helpers. Long-only now; shaped for shorting/margin later.
- `orders.py`: market BUY/SELL as a pure function over a `World`, with funds/holdings
  validation.
- Serializable world state: `to_dict`/`from_dict` + `save_world`/`load_world`. Save blob
  carries dynamic state only; static metadata reloads from the deterministic seed files.
- `advance_tick()` ticks the clock only (the V0.3 layered engine plugs in here).
- Tests `tests/test_world.py` all pass; `scripts/demo_world.py` smoke demo round-trips
  a saved world byte-identically.

**Gotcha (environment):** writing files to the mounted folder via the editor tool
truncated one file silently (a 977-byte `__init__.py` landed as 407 bytes). Rewriting via
the shell fixed it. Worth a quick size-check after editing on this mount.

**Next (V0.3):** the layered tick engine — Era→Minute, seeded anchors, the price forces
(design.md §4.1, §5). This is the "feel" milestone.

## 2026-06-14 — V0.3 layered tick engine ✅ (+ V0.4 validation)

- `engine.py`: prices are a **pure function of (world_seed, tick)** built from layered
  seeded value noise. Slow wander (Era/Cycle/Session, Brownian amplitude ∝ √period) gives
  realistic multi-day random-walk behaviour while mean-reverting to fundamentals; a small
  bounded Hour+Minute oscillation provides live motion and the "green-then-tank" hour
  mechanic. Global sentiment + interest-rate processes + sector trends create correlation.
- `MarketEngine` is stateless over a World (nothing extra to serialize); `advance_to(tick)`
  makes fast-forward/replay O(assets) not O(ticks).
- Per-kind price models: stock (drift+noise+sentiment+sector), crypto (weak anchor, strong
  sentiment for weak-anchor coins, stablecoins ~flat), bond (PV at evolving rate+credit).
- Profile ladder wired (Calm→Apocalyptic vol multipliers).

**Validation (`scripts/validate_engine.py`, `validation_chart.png`):**
- Daily return std: Calm 2.2% → Normal 3.1% → Volatile 5.1% → Apocalyptic 6.5% (monotone).
- Prices bounded over 2yr (≈2.5x median range) — mean-reverting, no explosions.
- Bonds move inverse to rates; stablecoin ~flat; meme coins wild; stock/crypto correlate
  via sentiment. Fast-forward == step-through to ~1e-9.
- Chart looks convincingly market-like.

**Notes / future tuning:** weekly return std (~18%) runs hot vs daily — the Cycle layer's
period-scale reshuffle. Fine/lively for a game; revisit in V0.5 profile tuning if desired.

**Env:** the mounted-FS editor-write truncation bit again (engine.py lost its tail mid-edit);
rebuilt via a shell write. Continuing to size-check after edits on this mount.

**Next (V1.1):** portfolio + orders behind a minimal UI with save/load — first playable.

## 2026-06-14 — V0.5 Profiles ✅

- New `trader_pro/core/profiles.py` — `MarketProfile` + the locked 8-level scale as the
  single source of truth. Each profile carries vol/sentiment/rate multipliers (live now)
  plus forward-looking knobs: event_rate_mult & cascade_mult (V1.4 drama) and
  predictability (V1.5 prediction accuracy, §5.4).
- Refactored `engine.py` and `world.py` to consume profiles.py (back-compat aliases kept:
  ProfileCoeffs, PROFILE_COEFFS); no behaviour change, all prior tests still green.
- `tests/test_profiles.py`: canonical order, Normal==unit baseline, all chaos knobs
  monotonic up, predictability monotonic down, unknown-profile error.
- `scripts/compare_profiles.py` -> `profiles_chart.png`: same stock/seed under all 8
  personalities — shared trend skeleton, amplitude escalating Calm→Apocalyptic.
- design.md §4.5 updated with the locked coefficient table; §10 item 3 resolved.

**This completes the entire V0 milestone (V0.1–V0.5).**

**Next (V1.1):** portfolio + orders behind a minimal UI with save/load — first playable.

### Handoff — git (for Matthew)
The repo is initialized (`.git/` exists) but has **no commits yet**, no identity set, and a
stale `.git/index.lock` I can't remove (mount denies the unlink). To make the first commit:

```
cd "<the Trader Pro folder>"
del .git\index.lock        # (Windows) remove the stale lock
git config user.name  "Matthew"
git config user.email "matthewcarven@gmail.com"
git add -A
git commit -m "V0 complete: seed data, world model, layered engine, profiles"
```
Everything is already covered by `.gitignore` (saves/, __pycache__, etc.).

## 2026-06-14 — V1.1 first playable (CLI) ✅

- `trader_pro/cli.py`: `TraderApp` over World+MarketEngine with a pure, testable
  `execute(line)->str` and a thin interactive `repl()`. Entry points: `play.py` and
  `python -m trader_pro`.
- Commands: market / stocks / bonds / crypto / find / look (with ASCII sparklines),
  buy & sell (by qty or `$amount`, plus `sell all`), port (live P&L), step / hour / day /
  next / run (speed control, §5.5), save / load, help, quit. ANSI colour when a TTY.
- World setup flow: choose profile (1–8) + seed + starting cash.
- `tests/test_cli.py` (7 tests): symbol resolution, buy→advance→sell realizes P&L, $-buys,
  overspend rejection, clock, save/load round-trip, unknown command. All green.
- Manual scripted session confirms prices move as time advances and P&L flows correctly.

**Full suite: 5 files, 30+ tests, all passing.**

**Next (V1.2):** flesh out stocks+bonds play and the speed/auto-run loop; then V1.3
crypto already tradable → add margin & short selling.

## 2026-06-14 — V1.3 margin & short selling ✅

- Rewrote `portfolio.py` to a **unified signed model**: positions can be negative (shorts),
  cash can be negative (margin debt). Added equity / gross_exposure / buying_power /
  maintenance_excess / is_margin_call. `apply_fill` handles open/extend/reduce/flip-across-zero.
- Margin ratios: INITIAL 0.50 (2:1 leverage), MAINTENANCE 0.25.
- `orders.py`: initial-margin check on any exposure-increasing trade; reducing always
  allowed. New `liquidate_for_margin(world)` force-closes largest-first until maintenance
  is restored (the hook V1.4 cascades will use).
- CLI: `short` / `cover` commands; `buy` now leverages up to 2:1; `port` & header show
  gross exposure, buying power, margin debt, and a ⚠ MARGIN CALL flag; advancing time
  auto-liquidates underwater accounts and prints the forced closures.
- Tests: updated `test_world` for the new short behaviour; new `tests/test_margin.py`
  (leverage cap, over-leverage reject, short profits on a drop, long→short flip, margin-call
  liquidation). **Full suite: 6 files, all green.**
- Demo: a 1.5x short in a Volatile world got margin-called and liquidated for a −70% hit —
  the "epic fail" path works end to end.

**Next (V1.2 backfill / V1.4):** richer stock/bond UX & live run loop polish; then V1.4 —
discrete events, black swans, and crash *cascades* (using event_rate_mult / cascade_mult).

## 2026-06-14 — V1.4 events, black swans & crash cascades ✅

- New `trader_pro/core/events.py`: a **seeded, deterministic** event schedule so prices stay
  a pure function of (seed, tick) — fast-forward/replay still exact. Events apply a decaying
  log-price impact over a bounded look-back window.
  - Micro (single-asset earnings / crypto moves), macro (sector rotations), and **black
    swans** — rare market-wide plunges that spawn a burst of correlated **aftershocks**
    (the cascade) over the following days, with slow partial recovery.
  - Frequency scales with profile.event_rate_mult; swan severity & aftershock count with
    cascade_mult. Black swans/yr: Calm 2 → Normal 4 → Volatile 14 → Apocalyptic 19.
- Engine: stocks/crypto take the log impact (stablecoins shrug it off via fundamental
  strength); bonds get an inverse **flight-to-safety** bump when the market drops.
- CLI: `news` command (recent headlines) + event tickers and a ▼ MARGIN-CALL cascade
  surfaced when you advance time. Headlines are templated per event kind.
- Tests `tests/test_events.py` (5): determinism, fast-forward-exact with events, swan
  frequency scales with profile, a swan really crashes the market, news/fired_between.
- `scripts/cascade_demo.py` -> `cascade_chart.png`: a Volatile-world flash crash with
  44 aftershocks; market index −60%, crypto craters, **bonds jump on flight to safety**.

**Daily-vol now includes fat tails: Calm 2.4% → Normal 5.6% → Volatile 18% → Apocalyptic
36% (events-driven crashes). Lively; high-profile severity is a balancing knob for later.**

**Full suite: 7 files, ~40 tests, all green.**

**Next (V1.5):** loans (no game-over) + buyable predictions (accuracy capped by profile
predictability). Then the TUI front-end Matthew wants.

## 2026-06-14 — V1.5 loans & buyable predictions ✅  (V1 milestone complete)

- Loans (`portfolio.py`): `Loan` model; `take_loan` with APR by leverage ratio
  (6/12/22/35%), borrow limit ≈2× net worth + $1,000 hardship floor (always a way back in);
  per-minute compounding via `accrue_interest`; `repay` (highest-APR first); `net_worth`
  nets out debt. Serialized. `world.net_worth()` now subtracts loans. No game-over.
- Predictions (`predictions.py`): seeded forecast of an asset's future price; noise =
  (1−profile.predictability)·√horizon, so Calm worlds are sharp, Apocalyptic fuzzy; cost
  scales with obscurity (mega-cap cheap, small-cap/crypto dear) and horizon. Deterministic
  per (seed, tick, asset, horizon) — no save-scum rerolls.
- CLI: `loan` / `repay` / `predict` commands; header & `port` now show net worth (with
  return), loan balance, and margin debt; loan interest accrues as time advances.
- Tests: `test_loans.py` (6) + `test_predictions.py` (4). **Full suite: 9 files, ~50 tests,
  all green.** Demo confirms the wipeout → loan → forecast → trade-back → repay loop.
- design.md §10 items 1 & 2 marked resolved with the locked numbers.

**🎉 V1 is feature-complete: 4 asset classes, longs/shorts/leverage, margin calls, 8 market
personalities, events + black-swan cascades, loans, predictions, save/load, seeded worlds.**

**Next:** the **TUI** front-end Matthew wants (Textual/rich over the existing TraderApp), or
balance-tuning the high-volatility profiles. V2 (web) / V3 (multiplayer) later.

## 2026-06-14 — Textual TUI front-end ✅

- New `trader_pro/tui.py`: a Textual app wrapping the existing `TraderApp` (same logic as
  the CLI). Live **ticking** market board (DataTable), status header with speed indicator,
  positions pane, scrolling news log (events + margin calls), and a `:` command line where
  every CLI command works. Launcher `play_tui.py` / `python -m trader_pro.tui`.
- Time control: Space play/pause, `[` / `]` speed (Slow→Turbo via a real-time timer),
  s/h/d to step a minute/hour/day. Vim-style: board focused by default, `:` for commands.
- Headless pilot test `tests/test_tui.py`: board renders, command-mode buy fills, Space
  starts the live clock and it advances, speed control responds. Green.
- `requirements.txt` corrected (core = stdlib only; textual + matplotlib optional).
  `tui_preview.png` shows the interface.

**Full suite: 10 test files, all green.** This is the TUI Matthew wanted (memory note done).

**Next ideas:** balance the hot high-vol profiles; persist watchlist; a price-chart panel
in the TUI; then V2 (web) when ready.

## 2026-06-14 — TUI fixes (browse-to-board, modal help) ✅

- Bug (from Matthew's screenshot): browse commands like `stocks` dumped a full-width CLI
  table into the narrow side log → overflow bleeding across the board/portfolio panes.
- Fix: redesigned TUI command routing —
  - **Browse** (`market`/`stocks [n]`/`crypto`/`bonds`/`find`/`watch`) now **repopulate the
    main board** and set its border title; they no longer print wide tables anywhere.
  - `look <SYM>` → compact card (price/Δ/sparkline) in the log; `help`/`?` → a scrollable
    **modal screen**; `port` → no-op note (positions already live in the side pane); `clear`.
  - Only short confirmations (trades, loans, predictions, events, margin calls) hit the log.
- Added rounded borders + titles to the board ("MARKET · <view>") and log ("news & log");
  `overflow-x: hidden` on the log. `?` keybinding opens help.
- Pilot test still green; full suite (10 files) green. Refreshed `tui_preview.png`.

**Note for Matthew:** give it another run — `stocks`, `find tesla`, `crypto`, `look NVDA`,
`?` for help should all behave now. Flag anything else that looks off.

## 2026-06-14 — TUI: keyboard views + trade dialog ✅

- Number keys switch the board view: **1** crypto · **2** stocks · **3** bonds · **4** watchlist
  (new `action_view_*`, also still available as typed commands).
- **Enter** on the highlighted board row opens a **TradeDialog** modal: shows price, your
  holding, cash & buying power; a quantity box (`10` / `$500` / `all`); and Buy / Sell /
  Short / Cover buttons (wired straight to `execute_order`, so margin rules apply). Result
  goes to the news log; rejections show inline.
- Fixed a CSS leak: the app-level `Input { dock: bottom }` was pulling the dialog's quantity
  box to the screen bottom — scoped it to `#cmd`, and the App now ignores non-command
  inputs (dialog input `event.stop()`), so a dialog quantity is never run as a command.
- Pilot test extended: number-view switching + dialog buy & short. Full suite (10) green.
  `tui_trade_dialog.png` shows the dialog.

## 2026-06-14 — TUI: paginated board ("→ Next 25") ✅

- The board now **pages** instead of capping at N. In a kind/find view it shows the current
  view's holdings pinned on top, then `page_size` (25) assets you **don't** own, then a
  "→ Next 25  (page X/Y)" row. Selecting that row loads the next page (wraps at the end) and
  resets the cursor to the top. Watchlist (4) and small classes (crypto 12, bonds 22) show
  no Next row.
- Refactor: `view_ids` → `view_source` (full candidate list) + `view_page` + `page_size`;
  `_board_ids` → `_visible()` returning (ids, next_label); `__next__` sentinel handled in
  `on_data_table_row_selected`. Owned assets are pinned and excluded from the page candidates.
- Pilot test extended (page 1/21 → Next → page 2/21, owned pinned, crypto has no Next).
  Full suite (10) green. `tui_paging.png` shows the Next row.

## 2026-06-14 — TUI: "0" = owned-only view ✅

- Added key **0** → "owned" board view (just your open positions, no paging/Next row).
  `owned_only` flag short-circuits `_visible()`; any other view key clears it.
- Board view keys: 0 owned · 1 crypto · 2 stocks · 3 bonds · 4 watchlist. Help updated.
- Pilot test asserts the owned view; full suite (10) green.

## 2026-06-14 — Fix: trade dialog crash on rapid Enter ✅

- Bug (Matthew): hammering Enter on the buy dialog raised `ScreenStackError: Can't pop
  screen…`. Cause: after Enter #1 fills the order and dismisses the dialog, queued Enter
  keypresses still reach the (now-closing) input → `on_input_submitted` → `_act` → a second
  `dismiss()` on an already-popped screen.
- Fix: made the dialog action idempotent. `_act` early-returns if `self._closing`; a single
  `_close()` helper sets the flag and dismisses **at most once**, guarded by
  `if self in self.app.screen_stack`. `on_input_submitted`, button presses and Esc all route
  through it. So a stuck/rapid Enter is a harmless no-op now, never a crash.
- TUI pilot suite still green (sandbox was flaky running the async harness repeatedly, but
  `test_tui.py` exits 0; guard verified by inspection too).

## 2026-06-14 — Fix: empty quantity no longer auto-buys ✅

- The trade dialog defaulted an empty quantity box to "1", so a stray Enter on a freshly
  opened dialog silently placed a 1-unit BUY (this is what actually happened in Matthew's
  crash trace — an unintended AAPL buy, then the ScreenStackError on the repeat Enters).
- Fix: `_act` now reads the raw quantity; if it's empty it shows "enter a quantity first"
  and returns without ordering. No more accidental fills from a stray Enter/click.
- Verified by inspection + the 9 non-TUI suites are green. (The Textual pilot test couldn't
  be run to completion this session — the sandbox kept timing out the async UI harness under
  load — but the change is a 3-line guard in `TradeDialog._act`.)
