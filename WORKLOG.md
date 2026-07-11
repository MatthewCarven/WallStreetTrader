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

## 2026-06-15 — Fix: freeze after buying in the TUI dialog ✅

- Bug (Matthew): buying via the trade dialog (Enter on a row → Enter to buy) froze the app.
- Root cause: the dialog called `dismiss()` **synchronously inside the Input.Submitted /
  key handler** that triggered the buy. Tearing the modal down mid-event deadlocks Textual's
  loop. (Traced it down with file-logged headless repros — `_act`/`refresh`/`dismiss` all
  complete, but the event never settles.)
- Fix: the dialog's button/submit/cancel handlers now schedule the action via
  `self.app.call_later(...)`, so `_act` (and its `dismiss`) run **after** the keypress event
  finishes — never mid-event. Removed the old timer/`call_after_refresh` deferral that
  didn't fire.
- `tests/test_tui.py` reworked to open the dialog via Enter, verify it's a `TradeDialog` and
  that `_amount()` parses `$`/qty, then dismiss via the test driver (a `run_test` pilot quirk
  makes keypress-driven dismiss not "settle" in-harness; the app itself is fine). Full suite
  (10 files) green.

**For Matthew:** relaunch and try buying through the dialog — it should no longer freeze.

## 2026-06-15 — Trade-dialog freeze: still happening, root-caused (NOT yet fixed)

The "should no longer freeze" above was wrong — the `call_later` change did **not** fix it.
Matthew hit it again: buy a crypto, the dialog closes, then the whole TUI freezes and Ctrl-C
won't quit. Reproduced and root-caused this session; **game code left unchanged** (capturing
data first, fixing later, per Matthew's call).

**Root cause:** dismissing `TradeDialog` runs Textual's screen teardown
(`pop_screen → do_pop → _replace_screen → screen.remove()`), which waits on the dismissed
dialog's child widget message-pump tasks. They never finish, so `do_pop` is stuck forever, the
event loop parks idle and stops dispatching input. Ctrl-C is dead because the terminal is in
raw mode (Ctrl-C is an unread keystroke, not a signal). Proven with a live asyncio task dump
(`do_pop` + all dialog widgets `done=False`) and a faulthandler thread dump (loop idle in
`select`, input thread alive).

- Not version-specific (reproduced on Textual 1.0.0 **and** 8.2.7); not crypto-specific;
  cancel-with-Esc freezes too. Content/layout-sensitive — the four `Button`s are a strong
  contributor; a bare `Static + Input` modal tears down fine.

**Captured (this session):**
- `docs/freeze-bug/README.md` — full write-up + fix directions.
- `docs/freeze-bug/asyncio-task-dump.txt`, `docs/freeze-bug/thread-stacks.txt` — the evidence.
- `tests/test_tui_trade_dialog_freeze.py` — cross-platform regression test (subprocess +
  timeout, Windows-safe). Marked **xfail** until fixed; XPASS will flag the fix.
- `scripts/repro_trade_dialog_freeze.py` — minimal repro (headless default; `--pty` for Unix).

**Next:** decide fix direction — robust (route Enter-on-row to the working command line) vs.
keep-the-popup (shrink/guard the modal's widget tree, verify repeatedly). See the README.

**For Matthew:** the dialog still freezes — until it's fixed, trade via the command line
(press `:` then e.g. `buy BTR $500`), which is unaffected.

### Button-count experiment (Matthew's ask: "no buttons, one, two?")

Tested the dialog with **0, 1, 2, 3, 4** Buttons in the real app (headless `run_test`, validated
against the live PTY): **every count freezes on dismiss**. So the Buttons are *not* the cause —
earlier notes that fingered them were wrong. Also ruled out, one factor at a time: dismiss style
(`call_later` vs direct), where info text is built (`compose` vs `on_mount.update`), and the
`on_input_submitted`/`_act` handlers — none flip it. A separate near-identical minimal modal
class stays alive, so it's a fragile teardown race in *this* screen, not any one ingredient.

Added `tests/test_tui_dialog_button_count.py` — parametrized over button count (xfail until
fixed). Also switched both freeze tests to an `xfail(strict=False)` decorator so they XPASS
(and flag themselves) the moment the dialog is fixed.

### Resolved (for now): it's a Textual regression → pinned `textual<0.72`

Swept Textual versions against the unmodified dialog (headless bisect). The freeze is a
**regression introduced in Textual 0.72.0**:

  0.50 / 0.68 / 0.70 / **0.71 = last good**  →  **0.72 = first bad** / 0.73 / 0.77 / 0.86 / 1.0 /
  8.2.7 / dev `main` (all frozen).

Matthew chose the quick win: **pinned `textual>=0.50,<0.72` in `requirements.txt`.** Verified the
real game (PTY, not just headless) under 0.71.0: open dialog → buy → dismiss → board still
responds → quits cleanly. The two freeze tests are now version-gated: they **pass** on
textual<0.72 (real guard) and **xfail (strict)** on >=0.72 — so an XPASS on a new Textual will
flag that the upstream fix landed and the cap can be lifted.

**To apply on your machine:** you likely have a newer Textual installed, so downgrade with
`pip install "textual<0.72"` (or `pip install -r requirements.txt`). Then `python play_tui.py`
and buy away.

**Still open (optional, later):** rebuild the dialog so it's version-proof and report the
regression upstream to Textualize — then the cap can go. Tracked, not urgent.

### Second bug, unmasked by the downgrade: `NoMatches('#log')` on buy → fixed

After pinning to 0.71.0 the freeze was gone, but **buying crashed**:
`NoMatches: No nodes match '#log'`. Cause: `TradeDialog._act` called `self.app._log(...)` and
`self.app._refresh()` **while the modal was still on top**, reaching into the main screen's
widgets. On Textual 0.71.x `app.query_one` can't see the base screen from inside a modal (newer
Textual happened to allow it — which is why the freeze hid this until now).

**Fix (applied to `trader_pro/tui.py`):** the dialog no longer logs/refreshes itself. On a fill
it just `self.dismiss((verb, qty, sym, result))`; on reject it shows the message and stays open.
`TraderTUI.push_screen(TradeDialog(aid), self._on_trade_closed)` now passes a callback, and
`_on_trade_closed` does the log + board refresh **on the app, after the modal has popped**. Also
dropped the `call_later` indirection in the handlers (dismiss straight from the handler).

Verified on **textual 0.71.0** (real terminal + headless): open dialog → `$100` buy → fills,
logs, board refreshes, position shows, app still responds, quits cleanly; cancel also clean; a
rejected order shows its message without crashing. On **>=0.72** it still freezes (xfail).
Updated `tests/test_tui_trade_dialog_freeze.py` to drive a real **buy** (was cancel-only), so a
regression of either failure mode is caught.

**Net:** on the pinned Textual the trade dialog now works end to end. Pull is automatic — the
edits are already in `trader_pro/tui.py`; just re-run `python play_tui.py`.

## 2026-06-15 — TUI: show the highlighted asset's full name

Seed data already carries names for all 537 assets (real S&P 500 names for stocks; invented for
crypto; descriptive for bonds) via `World.name_of()`, so nothing to scrape.

Surfaced it in the UI: as you move the board cursor over any stock / crypto / bond, the full name
now shows in the **previously-blank 4th row of the status block** (the unused row above the board),
e.g. `▶ AAPL  Apple Inc.   · Stock`. Implementation in `trader_pro/tui.py`:

- `_refresh()`'s status rendering was extracted into `_render_status()`, which now appends the
  name line for `self.cursor_aid`.
- New `on_data_table_row_highlighted` handler tracks the highlighted asset and calls
  `_render_status()` only (not a full board rebuild), so scrolling stays snappy and doesn't fight
  the cursor.

Verified on Textual 0.71.0 (real terminal): the name updates live while arrowing through stocks
and crypto, sits cleanly in the top row, and buying/refresh still work.

## 2026-06-15 — Starting capital → $5,000 cash ($10k buying power)

Matthew wanted "$5k cash + $5k loan = $10k". Went with the **margin** reading (his pick): the
game's automatic 2:1 margin already turns $5,000 cash into ~$10,000 buying power, so no new
mechanic — the extra $5k is the leverage. Changed the default starting cash 2500 → **5000** in
both entry points: `run_tui()` (`trader_pro/tui.py`) and the CLI prompt/default
(`trader_pro/cli.py`, now `starting cash [5000]`). The explicit `loan` credit line is untouched
(still ~2× net worth) and available on top if he wants it. Verified the TUI opens at
`cash $5,000.00 · buying power $10,000.00`.

## 2026-06-15 — Net-worth sparkline ("bells and whistles")

Added a live equity chart to the TUI. We discussed it first: because prices are a pure function
of `(seed, tick)`, saves never store price history and charts cost O(points drawn) — the only
thing that needs recording is the *player's* net-worth curve (it depends on your trades, not the
seed). So that's all we store, and it's small.

- **Core** (`portfolio.py`): new `nw_history` list of `(tick, net_worth)` on `Portfolio`, with
  `record_net_worth(tick, price_of, cap=240)`. **Bounded** — past `cap` points the series is
  halved (keep every other), so it stays fixed-size no matter how long you play. Serialized in
  `to_dict`/`from_dict` (backward-compatible: old saves load with an empty history).
- **Recording** (`cli.py`): `TraderApp._advance` records a point each time the clock moves; the
  initial point is seeded at construct/load. (Trades don't move net worth at the instant of the
  fill — cash and holdings offset — so time-advance is the right sampling moment.)
- **TUI** (`tui.py`): new bordered `#equity` panel at the top of the right column — current net
  worth + total return (green/red), a sparkline of the curve, and `hi / lo / N points`.

Verified on Textual 0.71.0 (real terminal): buy something, advance days, watch the sparkline
track the curve; save/load preserves history; save stays ~22 KB (constant — dominated by the
price snapshot, not history); the 240-cap holds; all 46 core tests still pass.

## 2026-06-15 — Brokerage fees: a difficulty dial (off → diabolic)

The direct counter to the frictionless-scalping exploit Matthew spotted: a per-fill commission,
selectable as **off / low / medium / high / greedy / diabolic**. Friction taxes turnover, so you
can't flip tiny wobbles for free anymore.

- **`orders.py`**: `FEE_RATES` (off 0%, low 0.10%, medium 0.30%, high 0.60%, greedy 1.20%,
  diabolic 2.50% — *per fill*, so ~2× that round-trip). `execute_order` deducts the commission
  from cash and from the net realized tally, and reports it on `ExecutionResult.fee`.
- **`world.py`**: `WorldConfig.fee_level` (default `off`), serialized — saves remember it.
- **`cli.py` / `tui.py`**: a `fees [level]` command (view or set, live) shared by both front-ends,
  a new-game prompt (CLI), the level shown in the status bar (`… · fees diabolic · …`), the fee
  shown in trade confirmations / the news log, and help entries.

Tuning check (a $1,000 round-trip): off $0 · low $2 · medium $6 · high $12 · greedy $24 ·
diabolic $50. The intended bite: a +4.5% scalp on $1k nets +$39 at medium, +$21 at greedy, and
**−$5 (a loss) at diabolic** — exactly killing free scalping at the top tier.

Verified on Textual 0.71.0: `fees` command sets the level live, status bar + trade log show it,
save/load round-trips `fee_level`, and all 46 core tests still pass. (Default stays `off`, so
existing play is unchanged until you opt in.)

## 2026-06-15 — Ctrl+N: new world (in-TUI)

`Ctrl+N` in the TUI opens a small keyboard-driven modal (`NewWorldScreen`) that asks the same
questions the CLI's new-world prompt does — profile / seed / starting cash / fees — pre-filled
with the current game's settings (seed re-rolled to a fresh random number). Enter starts, Esc
cancels, Tab moves between fields. No Buttons (matches the TradeDialog pattern that's safe on the
pinned Textual).

- `TraderApp.start_world(world)` (`cli.py`) swaps in a fresh world: new engine, re-seeded equity
  chart — the same setup as construction.
- `tui.py`: the modal, the `ctrl+n` binding, `action_new_world`, and `_on_new_world` (builds the
  world, resets view/cursor/playing state, clears the log, refreshes). Fields are validated/
  defaulted (bad profile → current, bad number → current, unknown fee → current).

Verified on Textual 0.71.0 (real terminal): Ctrl+N opens the form (fields pre-filled), Esc leaves
the game untouched, Enter starts a fresh market (seed re-rolled, net worth reset to the stake,
board/sparkline reset), the app stays responsive, and the modal tears down with **no freeze**.
46 core tests still pass.

## 2026-06-30 — TUI V1.6: price-chart pane, top movers, sorting + a retro skin

Matthew picked three TUI upgrades. All landed together; 55 tests pass (Textual 0.71.0).

**Price-chart pane** (`tui.py`). A new bordered `#chart` panel in the right column, between the
net-worth panel and the portfolio list. It draws the *highlighted* asset's recent price path as a
multi-row filled area chart — full blocks plus an 8-level fractional top cell, so a 7-row panel
gives ~56 levels of vertical resolution (`area_chart()`). The range cycles **1H → 1D → 3D → 1W**
with the **`c`** key. It redraws on cursor-move (same hook as the name line) so arrowing the board
flips through charts instantly, and it sizes itself to the panel (`panel.size`), so it adapts to
the terminal. Series come straight from `engine.series(aid, start, t+1, step)` — ~26 price points,
cheap, and nothing extra to store (prices are still a pure function of seed+tick).

**Top movers + sorting** (`tui.py`). New **`5`** / `movers` view lists the 10 biggest 1D% gainers
and 10 biggest losers across the whole market, with green **▲ TOP GAINERS** / red **▼ TOP LOSERS**
separator rows (`_movers()`, special-cased in `_refresh`). Separately, **`o`** / `sort` toggles the
current board view between natural order and **1D % descending** (`_visible` sorts the candidate
page; the title shows `↓%`). Shared `_chg1d()` helper backs movers, sorting, the ticker, and the
board's 1D% column. Movers recomputes ~537 changes on refresh, only while that view is open.

**Retro skin** (`tui.py`). A green-phosphor palette (CSS: dark `#07120b` ground, green/amber panel
borders), amber title/sub-title, and an **amber scrolling ticker tape** docked under the header
(`#ticker`): watchlist symbols + price + ▲/▼%, rebuilt each refresh and sliced by a per-timer
offset for the marquee scroll. The clock-timer now early-returns whenever a modal is up
(`len(self.screen_stack) > 1`) — the market pauses behind Help/Trade/New-world and, crucially, the
ticker stops querying base-screen widgets that aren't in the modal's scope (was a `NoMatches` crash).

New regression test `tests/test_tui_features.py`: area-chart shape, ticker scroll, chart-range
cycling, movers ordering + row count, the sort toggle, and the modal/timer guard.

**Process note (for next time):** the editor file-write truncated `test_tui_features.py` mid-file
again on this mounted folder, and pytest's rewritten-assert cache went stale (mount mtime is
coarse), so edits silently ran old bytecode. Fix that bit me for a while: write to the mounted
folder via the shell (heredoc), and run pytest with `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`
after `rm -rf` of `__pycache__`. Matches the standing "shell writes are reliable" note.

## 2026-06-30 — V1.7: persistence — autosave & resume, a save/load UI, slot browser

Save/load already existed at the core (`save_world`/`load_world`, schema-versioned JSON). This
milestone makes it first-class. 63 tests pass (8 new). Matthew picked autosave+resume, the in-TUI
UI, and named slots/browser.

**New `trader_pro/persistence.py`.** Wraps `World.to_dict()` and adds:
- `save_game(world, path, label=)` — embeds a small `"meta"` envelope (net worth, return %, clock,
  profile, fee level, timestamp, #positions) so the browser can summarise a slot without rebuilding
  the engine. Writes are **atomic** (temp file + `os.replace`), so a crash mid-write — including the
  frequent autosave — can never corrupt an existing slot. `from_dict` ignores the extra key, so old
  and new saves stay cross-compatible.
- `read_info(path)` → `SaveInfo`; derives net worth for pre-meta saves from `nw_history` or, failing
  that, straight from the blob (cash + Σ qty·price − loans). Flags corrupt files instead of throwing.
- `list_saves` (newest first), `delete_save`, and `slot_path` / `autosave_path` / `has_autosave`.
- `cli.py`'s `_save`/`_load` now route through it (the CLI `save`/`load` commands get meta too).

**Autosave + resume** (`tui.py`). Autosaves to the `autosave` slot on quit (`q`, Ctrl+Q, Ctrl+C —
best-effort, never blocks exit) and periodically while playing (wall-clock throttled to every 30s,
so speed/turbo doesn't hammer the disk). `run_tui()` resumes the autosave on launch if present and
logs a banner with the restored clock + net worth; Ctrl+N still starts fresh. The clock-timer
already early-returns while a modal is up, so no autosave fires behind a dialog.

**Save/load UI** (`tui.py`). **Ctrl+S** → `SaveScreen` (name input, sanitised to `[A-Za-z0-9_-]`).
**Ctrl+L** → `LoadScreen`, a slot browser (DataTable: slot · net worth · return · clock · profile ·
age), Enter to load, `x` to delete (press twice to confirm), Esc to cancel; the `autosave` slot is
listed and tagged `(auto)`. The `save` / `load [name]` / `saves` commands share the same paths.
Loading reuses `TraderApp.start_world` (preserves the loaded equity history) plus a new
`_reset_view_after_swap()` shared with Ctrl+N.

**Bug found & fixed:** a modal's DataTable `RowHighlighted`/`RowSelected` messages bubble up to the
*app's* handlers, which then query base-screen widgets (`#status`) that aren't in the modal's scope
→ `NoMatches` crash. Fixed by `event.stop()` in the modal and a `len(screen_stack) > 1` guard on the
app handlers (same guard the timer uses). Tests: `test_persistence.py` (roundtrip+meta, atomicity,
ordering, pre-meta/corrupt fallback, delete, autosave helpers) and `test_tui_persistence.py`
(Ctrl+S modal + sanitise, browser order, load-older, double-`x` delete, autosave, resume).

## 2026-06-30 — Guard against the Textual >=0.72 trade-dialog freeze at startup

Matthew hit the documented freeze in real play: buy ~$10k of BTR via the Enter trade dialog, the
dialog closes, and the TUI locks up — but the amber ticker keeps scrolling. That last detail is
the tell: the `set_interval` ticker timer keeps firing while Textual's screen-teardown wedges input
dispatch (see docs/freeze-bug/README.md). Confirmed by repro: the play→dialog→buy→close flow is
clean on the pinned 0.71.0 but hangs past a 45s timeout on 0.72.0. So his machine has Textual
>= 0.72 despite the `<0.72` cap in requirements.

Rather than rely on people reading the cap, `run_tui()` now calls a new `textual_version_ok()` and,
on >= 0.72 (incl. 1.x/2.x and rc tags), prints a clear message — what breaks, and
`pip install "textual<0.72"` — and **refuses to launch** instead of freezing on the first trade.
Tests in `tests/test_version_guard.py` (parser across 0.50→2.x, and that run_tui refuses + explains).
66 tests pass.

Proper long-term fix still open: the freeze is upstream in Textual's teardown of *this* ModalScreen;
the dependable cure is to move the trade UI off `ModalScreen` (an inline, non-modal panel toggled
with `display`), which would lift the version cap entirely. Flagged for a follow-up.

## 2026-06-30 — TUI: keep the board's row selection across time-advance / live play

Annoyance Matthew spotted: every `_refresh()` rebuilds the board with `table.clear()`, which snaps
the DataTable cursor back to row 0 — so pressing s/h/d, or just letting the clock run, kept yanking
the highlight (and the chart pane) back to the top.

Fix in `_refresh` (`tui.py`): capture the highlighted row's key before `clear()`, collect the new
row order, then restore the cursor — by the same asset if it's still listed, else by clamped
position. View switches (`_set_view`) now explicitly `move_cursor(row=0)` so changing class still
starts at the top (movers still lands on row 1; new-world/load reset as before).
`tests/test_tui_selection.py` covers it. 67 tests pass.

## 2026-07-10 — TUI: keep the board row fixed when you buy or sell

Matthew asked for the highlight to stay on the item when trading. Diagnosis (drove the TUI
headlessly first): the row-selection fix above *already* restored by asset, so buying a row kept it
selected — but holdings pin to the **top** of the board, so the cursor got yanked from (e.g.) row 6
up to row 0, and a full sell dropped it back down the list. That jump is what reads as "it didn't
stay put." Asked Matthew which he wanted; he picked **keep the same spot in the list** (so you can
trade down a list without being thrown to the top).

Fix (`tui.py`): `_refresh()` takes a new `keep_row` flag. On a trade we pass `keep_row=True`, which
restores the cursor by **row position** instead of by asset — the traded asset still moves into the
holdings block, but the cursor holds its place; the name line + chart re-sync to whatever asset is
under the cursor after the move. Wired into both trade entry points: `_on_trade_closed` (the Enter
dialog) and the command-line `buy`/`sell`/`short`/`cover`. Time-advance / live play still restore by
asset (unchanged, `keep_row=False`). New `test_selection_holds_row_across_trade` in
`tests/test_tui_selection.py`; full suite 68 pass.

Committed on its own (`d1e3168`), kept separate from the pre-existing unstaged `tui.py` WIP
(default-max trade quantity + the new "Cost / Share" column), which is left untouched for Matthew
to commit when he's ready.


## 2026-07-11 — TUI: configurable board columns (Ctrl+1..6 show/hide)

Matthew asked what the main-screen columns are and wanted to adjust which are visible. The board
shows six: Symbol, Price, 1D %, Pos, Value, Cost / Share (first three are market data, last three
are your holdings in that asset). He chose per-column hotkeys — hold Ctrl and press a number to
toggle that column — and session-only (no persistence).

Confirmed the mechanics headlessly before building: Textual 0.71 routes ctrl+1..ctrl+6 bindings,
`DataTable.clear(columns=True)` + `add_columns` rebuilds columns cleanly, and on Windows the console
driver delivers distinct Ctrl+digit events (the usual terminal byte-collision is a Unix/ANSI issue,
not Win32).

Refactor (`tui.py`): the board is now built from a declarative `BOARD_COLUMNS` spec
(id, header, render) instead of hard-coding cells in three places — `add_columns`, `_add_row`, and
the movers/"next page" separator rows (a new `_separator_row` helper emits exactly one cell per
*visible* column). `col_visible` holds state; Ctrl+1..6 call `action_toggle_column`, which flips a
column and calls `_rebuild_board_columns` (clear + re-add columns, repaint). The highlighted asset
is preserved across the rebuild (same care as the earlier row-selection fixes), and the last visible
column can't be hidden so the board never goes empty. Bindings are `show=False` (kept off the
footer) and documented in the help panel.

Drove the real TUI headlessly to verify: initial six columns, single/multi toggles, restore, movers
view + toggle (separators adapt), cursor preservation across a toggle, and the last-column guard —
all pass.

Committed as `7b225be`, on its own. This folds Matthew's earlier WIP "Cost / Share" column (and the
colored Value cell) into the committed spec, since it's part of "the columns." Deliberately left
untouched/unstaged: the other half of that WIP — the TradeDialog default-max trade quantity (empty
box → max buy/sell) — which is unrelated to columns and stays Matthew's to commit.

## 2026-07-11 — TUI: P&L % board column

Matthew asked for a column showing the % profit/loss he'd realise by selling now, off the new
Cost / Share basis. Added it as the 7th board column, "P&L %" (Ctrl+7 toggles it like the rest).

Formula (`_add_row`): `(price - avg_cost) / avg_cost * 100`, sign-flipped for shorts so a falling
price reads green (a short profits as price drops). Green/red on gain/loss, dim "·" when you hold
nothing. Fees ignored, matching the side panel's P&L. `pnl` is precomputed into `_RowCtx` (alongside
`chg`/`value`) so the render lambda stays a one-liner.

Verified headless: drove the TUI, opened a long and a short, advanced the clock, and checked both
cells against an independently-computed expected value (long −15.04%, short −5.63% — the short in the
red because price rose above entry), plus the flat-asset "·" and the Ctrl+7 toggle. Full suite: 68
pass.

Committed as `349ae70`. The TradeDialog default-max-quantity WIP is still left unstaged (Matthew's).

## 2026-07-11 — TUI: live play paced at 1 sim-minute per real second

Matthew found default play too fast (old "Normal" jumped ~40 sim-minutes per real second) and asked
it to "advance a second at a time." The engine ticks in whole minutes (HOUR=60, no sub-minute unit),
so we read that as one step per real second and confirmed the pace with him.

Reworked the play clock (`_on_timer`) from "advance N ticks every 0.3s timer fire" to "advance by
REAL elapsed wall-clock × the speed's ticks/second," accumulating fractional ticks against a
monotonic baseline. `SPEEDS` is now ticks-per-second: 1 / 10 / 60 / 600 = 1min / 10min / 1hr / 10hr
of sim-time per real second, default index 0 (the calm 1 min/s crawl). The 0.3s timer still drives
the marquee scroll. A per-fire cap (elapsed clamped to 1s) stops a stall (laptop sleep, GC) from
fast-forwarding; the baseline is dropped on pause or while a modal is up, so paused time is never
banked and resume doesn't jump. Confirmed `s` still steps exactly one minute (Matthew asked) — it was
already `_advance(1)`; there is no "second" to bind to.

New `tests/test_tui_timing.py` drives this deterministically by rebinding only tui's `time` name to a
shim clock (Textual/asyncio keep the real one, so their scheduling is untouched). Updated the
real-time smoke test in `tests/test_tui.py`: it waited 0.8s at the old fast default, which no longer
crosses the 1-tick threshold, so it now bumps to the top tier to observe the advance, then steps back
to the default. Full suite: 69 pass.

Committed as `95c244c`. The TradeDialog default-max-quantity WIP is still left unstaged (Matthew's).

## 2026-07-11 — GUI (V2): Slice 0 — PySide6 desktop shell & live clock

Kicked off a desktop GUI front-end — the V2 client from design.md §9, built as a native Python app
(PySide6) rather than the originally-sketched browser client. Matthew asked how to "carve out a GUI"
and we planned it together: 11 thin, independently-runnable slices at full TUI parity, on PySide6 +
pyqtgraph (LGPL, and no version-pin fragility like the Textual freeze). This is slice 0, the walking
skeleton.

The enabling fact, confirmed by mapping the reuse surface: the core is genuinely UI-agnostic and
`TraderApp` is already the shared controller the TUI leans on (`trader._advance` / `resolve` /
`start_world`). So the GUI is a thin Qt view layer over the same `TraderApp` + core reads — not a
rewrite — and the TUI is left completely untouched.

Structure quarantines the Qt dependency: `gui/model.py` holds the pure, Qt-free logic (the pacing
accumulator `steps_for`, the `boot` resume/new lifecycle, and `header_html`) so it imports and
unit-tests without PySide6; `gui/app.py` is the only module that imports Qt. `TraderGUI(QMainWindow)`
renders the dashboard header and drives a `QTimer` loop that mirrors the TUI's wall-clock accumulator
exactly — advance by REAL elapsed × the speed's ticks/second, default 1 sim-minute per real second,
same single-step stall cap. Boot resumes the last autosave or starts the seed-20260614 Normal world
(matching `run_tui()`); autosave fires on close. Launchers `python play_gui.py` and
`python -m trader_pro.gui` both print an install hint if PySide6 is absent. Deps are optional extras
in requirements.txt — PySide6 ships stable-ABI (abi3) wheels, so they install even on this box's
Python 3.14.

One real snag worth recording: PySide6 (shiboken) installs a global import hook that, on 3.14,
collides with Textual's lazy `textual.widgets.__getattr__` when both are imported into one
interpreter — it surfaces as `ImportError: ... has no class '__wrapped__'` during pytest collection
once the GUI and TUI test modules load together. The two front-ends never share a process in real
use, so the fix is to keep PySide6 out of the main pytest interpreter: the GUI smoke test runs
offscreen in a subprocess, while the pure model tests run in-process. Verified end-to-end — offscreen
widget construction + header/advance wiring, plus a live event-loop run that advanced the clock
D0 00:00 → 00:01 over ~1.6s of play (the expected 1 min/s). Full suite: 75 pass (67 + 8 new).

Committed as `61ec9b3`. Next: slice 1 (time & speed controls). The crypto-seed / build_seed / TUI
default-max-quantity WIP is still left unstaged (Matthew's).

## 2026-07-11 — Crypto: broaden the coin universe (12 → 36)

Matthew asked to add more crypto "companies," floating a web search. Did a quick survey of the live
2026 crypto sectors (CoinGecko narratives, CryptoRank Q2 recap) to ground the *categories* — RWA
(~$29B on-chain), DePIN (~$35B), AI compute (Render/Bittensor/Fetch shape), Layer-2 rollups, and
oracles — then invented a curated batch of **16 new fictional coins** across them. Kept everything
fictional on purpose: design.md §3.3 and §7.4 call for "a small hand-authored set of fictional
coins," and the existing names are riffs on real categories, not real coins. New coins are the same:
Linkchain (oracle), Kosmos/Polkabit (interop), TensorMind/Renderos/FetchWise (ai),
Helion/Fylecoin (depin), Arbitrix/Optimus (layer2), Ondine (rwa), Lidus (liquid-staking),
Binex Coin (exchange), plus depth in the existing buckets (Avalon platform, Bonko meme, Silvercoin
store-of-value). That takes the universe from 20 → 36 coins and 7 → 15 archetypes.

Source of truth is `scripts/build_seed.py` (`CRYPTO_DEFS`); added one `.extend([...])` block and
regenerated the seed JSON deterministically (`python scripts/build_seed.py`, seed unchanged at
20260614 — stocks/bonds rebuilt byte-identical). The engine only consumes the numeric fields
(`fair_value`, `volatility`, `fundamental_strength`, `circulating_supply`); `archetype` is a pure
display label (cli.py / models.py), so the new categories needed no engine work. Respected the one
seed invariant — every non-stablecoin coin keeps volatility ≥ 0.5 (test_seed.py).

One test needed a fix: `test_tui.py::test_tui_smoke` asserted the crypto board fit on a single 25-row
page (no "Next" row) — true at 12/20 coins, false at 36. Pointed that "small view → no Next row"
assertion at the bonds board (22, still one page) to preserve its intent. Full suite: **75 pass**.
Verified the coins load and render: 36 across 15 archetypes, new ones show correct fv/vol.

Committed the crypto seed (`build_seed.py`, `crypto.json`, `test_tui.py`) on top of Matthew's staged
coin WIP. Left the separate TUI default-max-quantity WIP in `tui.py` untouched (still Matthew's).
Commit is local — not pushed.
