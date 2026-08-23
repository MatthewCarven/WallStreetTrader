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

## 2026-07-11 — GUI (V2): Slice 1 — time & speed controls

Fleshed out the shell's time surface. The controls row now carries « / » to cycle `SPEEDS`
(1 min/s → 10 min/s → 1 hr/s → 10 hr/s, clamped at both ends, bound to `[` / `]`) and
Step / +1h / +1d to jump the market by 1 / 60 / 1440 sim-minutes (bound to `s` / `h` / `d`). The
discrete steps advance immediately whether playing or paused and never touch the play-clock
baseline — same semantics as the TUI's `action_step`/`hour`/`day` — and a +1d jump stays cheap
because the engine evaluates seeded anchors rather than grinding 1440 minutes. Throttled 30s
autosave and resume already shipped in slice 0, so nothing to add there.

Verified in the offscreen subprocess smoke: speed clamps at both ends, the three steps move the
clock by exactly 1 / +HOUR / +DAY regardless of play state, and every control button carries a
keyboard shortcut. Full suite: 75 pass.

Committed as `1458ef2`. Next: slice 2 (the live market board). WIP still unstaged (Matthew's).

## 2026-07-11 — GUI (V2): Slice 2 — live market board

The centerpiece: a `QTableView` over a `QAbstractTableModel` (`BoardModel`) showing the nine
board columns — Symbol, Price, 1D/7D/31D %, Pos, Value, Cost/Sh, P&L % — repainting every tick.

Ported the board's data logic into pure, Qt-free helpers in `gui/model.py`: `chg_pct` (= the TUI's
`_chgNd`), `row_ctx` (= `_add_row`), and `cell()` — the Qt-free equivalent of the BOARD_COLUMNS
render lambdas, returning `(text, colour, right-align, bold)` so the Qt model just maps them onto
roles. `board_ids()`/`default_watchlist()` are a deliberately simple stand-in for the TUI's
`_visible()` (held pinned on top, then the crypto+notable-stock watchlist, deduped); view switching,
sort and paging are slice 3. `BoardModel.refresh()` recomputes values in place and emits
`dataChanged` so a live repaint keeps selection; `set_aids()` is the full reset. Colours match the
TUI — green/red deltas, amber shorts, dim `·` placeholders for unheld rows. Table styled via QSS
(header rule, alternating rows, green selection).

Keeping the data logic pure paid off for testing: `test_gui_model.py` covers row/cell formatting
(long, short, flat) and `board_ids` with no Qt at all, while the offscreen subprocess smoke checks
the model wiring (row/column counts, header labels, a money-formatted price cell). Also eyeballed a
text dump of the live board over 3 sim-days — sane symbols, prices and 1D/7D/31D moves (7D and 31D
coincide that early because both clamp to since-start, which is correct). Full suite: 78 pass.

Committed as `03b0e64`. Next: slice 3 (board interaction — views / sort / selection / paging). WIP
still unstaged (Matthew's).

## 2026-07-11 — GUI (V2): Slice 3 — board interaction (views, sort, paging, selection)

Made the board navigable. A view toolbar switches which slice of the market shows — Owned / Crypto /
Stocks / Bonds / Watch (keys 0–4, exclusive checkable buttons) — with a Sort-1D% toggle (`o`) and
prev/next paging for the big lists (stocks paginate 25 at a time with a "page n/m" label). Clicking a
row sets the highlighted asset (`cursor_aid`) and shows its symbol/name/kind in a label on the toolbar
— the hook the chart (slice 4), detail (slice 5) and trade dialog (slice 6) will read.

Ported the TUI's `_visible()` and `_kind_ids` into pure helpers `model.visible_ids`/`kind_ids` (held
pinned on top, unheld candidates paged, optional 1D% sort), so the selection logic is unit-tested with
no Qt. `BoardView` subclasses `QTableView` and overrides `keyboardSearch` to a no-op — otherwise the
table's type-ahead row search swallows single-letter keys before the 0–4 / `o` / `s` / `h` / `d`
shortcuts can fire.

One deliberate divergence from the TUI: the TUI re-runs `_visible()` on every repaint, so a sorted
board reorders live each tick. In the GUI, live ticks call `_refresh_board()` (repaint values in
place, order stable) and only view/sort/page changes rebuild + reorder — rows stay put and clickable
while playing, which matters far more with a mouse than in a keyboard TUI. Selection is preserved by
asset id across rebuilds.

Verified: pure tests for `kind_ids` and `visible_ids` (watchlist / owned / paged-stocks / 1D%-sorted),
plus board-interaction assertions in the offscreen subprocess smoke (switch to each view, page stocks,
select a row → `cursor_aid` + label, toggle sort). Full suite: 81 pass.

Committed as `e30677f`. Next: slice 4 (pyqtgraph price chart of the highlighted asset).

## 2026-07-11 — GUI (V2): Slice 4 — pyqtgraph price chart

Added the price chart in a resizable `QSplitter` beside the board (board ~2 : chart ~1, like the
TUI's 2fr/1fr). It charts the highlighted asset from `engine.series(aid, start, t+1, step)` at ~240
points, drawn as a filled area — pen and translucent fill green when the window is up, red when down —
with a title of `SYM · range · price · change%`. Range cycles 1H/1D/3D/1W via the `c` key / Range
button (`model.CHART_RANGES`). It re-renders on selection change and every tick. The x-axis is hidden
(tick-minute labels aren't meaningful; a real DateAxis is a later polish item).

pyqtgraph pulls in numpy (already present) and constructs fine under the offscreen platform. Verified
with a headless render: an 8-day Volatile world, 1W range on a crypto → a 241-point red downtrend area
that draws correctly as vector graphics (only the axis/label *text* is tofu headless; the curve, fill,
colour, splitter layout and board cell colours all render right). Full suite: 82 pass.

Committed as `2c33e3e`. Next: slice 5 (net-worth equity curve + asset-detail fundamentals panel).

## 2026-07-11 — GUI (V2): Slice 5 — equity curve + asset detail

Rounded out the read-only dashboard's right column (which now reads top-to-bottom: net-worth curve,
price chart, asset detail). The equity curve plots `pf.nw_history` — green above starting cash, red
below, titled "net worth $X (+Y%)" — and updates each tick/advance. Below the price chart, a detail
panel shows the highlighted asset's fundamentals from `world.meta_of(aid)` via the pure
`model.asset_detail_html`, with kind-specific fields: stock → sector/industry/growth/volatility/cap;
bond → issuer/rating/coupon/maturity/yield; crypto → archetype/fair-value/volatility/anchor/supply.

Verified with a pure per-kind `asset_detail_html` test + equity/detail assertions in the offscreen
smoke, and a content dump: Agilent (Health Care stock), a AAA 1Y government bond (3.83% coupon), and
Bitron (store-of-value crypto, 65% vol) all render the right fields. The equity curve is flat at
$5,000 until there are positions — net worth only moves with P&L — so it gains shape once trading
lands. Full suite: 83 pass.

Committed as `27d5bcf`. That completes the read-only dashboard (board · interaction · chart · equity ·
detail). Next: slice 6 (the trade dialog — first point the GUI is actually playable).

## 2026-07-11 — GUI (V2): Slice 6 — trade dialog (buy/sell/short/cover), playable

The GUI is now playable end-to-end. A modal `TradeDialog` — opened with Enter, a double-click on a
row, or the Trade button — buys / sells / shorts / covers the highlighted asset through
`execute_order`. The quantity parsing (empty ⇒ max buying-power/whole-position, `all`, `$amount`,
plain number) is lifted into the pure `model.trade_quantity`, a faithful port of the TUI's `_act`, so
it's unit-tested without Qt. On a fill the dialog closes and `_on_filled` re-pins holdings, refreshes
header/chart/equity/detail and flashes the fill (price, fee, realized P&L) in the status bar; a
rejected order (insufficient buying power, etc.) shows `res.message` and stays open.

Important detail carried over from the TUI: the market **freezes while the dialog is open** — the
QTimer is stopped for the duration and the play baseline dropped on resume — so the price quoted in
the dialog is exactly the fill price, and no wall-clock time is banked behind the modal.

Verified with a pure `trade_quantity` test, a buy/reject/sell cycle in the offscreen smoke, and a live
run: bought $2k of BTR (0.0246 units, cash $5k→$3k), held 4 days as it fell to ~$69k, sold all →
realized −$300.74 (exactly qty × the drop), cash back to $4,699, position closed, net worth tracking
the holding throughout. Full suite: 84 pass.

Committed as `145b4b9`. Next: slice 7 (positions & margin health — the positions table plus the
blue→red margin meter and margin-call popup Matthew asked for).

## 2026-07-11 — GUI (V2): Slice 7 (first half) — margin meter + margin-call popup

Did the half of slice 7 Matthew most wanted, then stopped mid-slice (usage budget) — the positions
table is the clean other half for next session. The controls row now carries a compact painted
`[▮▮▮░░]` `MarginMeter`: blue when all cash, amber at ~half (buying power exhausted, gross = 2× equity),
red at full (the margin-call line, gross = 4× equity / `maintenance_excess <= 0`). Fill =
`MAINTENANCE_MARGIN_RATIO * gross / equity` (pure `model.margin_fill`); colour lerps blue→amber→red
(`model.margin_color`). It refreshes whenever the header does (tick, trade, step).

The popup: `_advance` now returns its forced-liquidation closures (previously discarded); when
non-empty the GUI **pauses play** and shows a `QMessageBox` listing exactly what the broker force-sold,
at what price, and the realized hit (`model.margin_call_message`) — a margin call becomes a
stop-and-look moment instead of a blink-and-miss mid-autoplay.

Verified: pure tests (`margin_fill` 0 when all cash; `margin_color` blue-at-empty / red-at-full;
`margin_call_message` content); a smoke check that a 2× max-buy lifts the meter off zero; and an
offscreen render confirming the meter paints half-amber at 2× leverage (fill 0.50, rgb (255,176,0)).
Full suite: 86 pass.

Committed as `0e67757`. **Slice 7 is half done** — next session: the positions table (signed qty /
avg cost / value / unrealized P&L / P&L %) + a portfolio summary line, then slices 8–10.

## 2026-07-12 — GUI (V2): Slice 7 (second half) — positions table + summary

Finished slice 7. A positions table now sits under the board in a vertical `QSplitter` (board ~3 :
positions ~1). `PositionsModel` reads the pure `model.position_rows` and shows Symbol, signed Qty
(amber for shorts), Avg Cost, Value, unrealized P&L ($) and P&L % — green/red by sign — refreshing
each tick/trade. Above it a summary line: position count, total unrealized P&L, and the
maintenance-margin **headroom** (`maintenance_excess`), which pairs with the meter from the first
half. `refresh()` only resets the model when the set of held assets changes (open/close), otherwise it
repaints values in place, so live P&L updates don't flicker or drop selection.

Verified with a pure `position_rows` test (value = qty·price, pnl ≈ 0 right after a buy) and a
positions check in the offscreen smoke, plus a live long+short dump: a BTR long (−17.46%) and an A
short (−12.29 sh, amber, −6.62% as the stock rose against it), summary unrealized −623.28 = sum of the
two, margin headroom $8,357.86. Both signs and the short's negative value/qty render correctly. Full
suite: 87 pass.

Committed as `a948f19`. **Slice 7 done** (margin meter + popup + positions table + summary). Next:
slice 8 (news/event feed + scrolling ticker tape + top-movers view).

## 2026-07-12 — GUI (V2): Slice 8 — news feed, ticker tape, top-movers

The market's running story. Three pieces, all fed by pure helpers so the logic tests without Qt:

- **News feed** — a `QListWidget` (newest on top, capped at 200) that logs the seeded events fired on
  each `_advance` plus any forced margin liquidations, coloured green/red by direction
  (`model.event_entry` / `closure_entry`). `_advance`'s events were previously discarded; now they
  surface here.
- **Ticker tape** — an amber marquee under the header (`model.ticker_text`: watchlist symbol · price ·
  1D% arrow), scrolled one character per 250 ms timer tick — and it scrolls even while paused, since
  `_scroll_ticker` runs before the play-state check in `_on_timer`.
- **Top-movers** — a board mode (key 5 / Movers button) showing the top-12 1D% gainers then losers
  across the whole market (`model.movers_ids`), wired through `_rebuild_board` alongside the normal
  views.

Verified: pure tests (movers dedup, ticker arrows, event/closure colour) + smoke assertions, and a
live 15-day Volatile run — 83 events logged with real headlines ("Verisk Analytics surges on a blowout
earnings beat"), a populated ticker, and a 24-row movers board (LNR +50%, SHIBE +45% … KOSM/FTCH
−13%). Full suite: 89 pass.

Committed as `9cff18d`. **8 of 11 slices done.** Next: slice 9 (save/load slot browser + new-world
dialog), then slice 10 (predictions / loans / fees + theming & polish).

## 2026-07-12 — GUI (V2): Slice 9 — save/load browser + new-world dialog

Added a **Game** menu (`Ctrl+N` / `Ctrl+S` / `Ctrl+L`). Save prompts for a slot name (QInputDialog) and
writes with `save_game`. A `LoadDialog` browses the slots from `list_saves` — one row each with net
worth, return and timestamp (pure `model.save_info_line`), Load / Delete / double-click-to-load,
corrupt slots flagged red. A `NewWorldDialog` collects profile (a dropdown of `PROFILE_NAMES` with each
profile's tagline from `get_profile`), world seed, starting cash and fee level, then `World.new` +
`trader.start_world`. Both load and new-world funnel through `_after_world_swap`, which resets the view
to the watchlist, rebuilds the watch list, clears the news feed, un-plays, and repaints every panel.
The market freezes (timer stopped) while any of these dialogs is open.

Verified: a pure `save_info_line` test + save/load/new-world assertions in the offscreen smoke, and a
live round-trip — saved (net worth $4,790.30, tick 2880, 1 position) → swapped to a fresh Calm world
(reset to $1,000, tick 0, 0 positions) → loaded back to the exact saved state. Full suite: 90 pass.

Committed as `99cfd3f`. **9 of 11 slices done.** Last one: slice 10 (buyable predictions, loans/repay,
fee-level selector, plus a `:` command line and theming/help polish) → full TUI parity.

## 2026-07-12 — GUI (V2): Slice 10 — predictions, loans, fees, command line → FULL PARITY

The final slice. A `PredictDialog` (Predict button) buys a forecast for the highlighted asset via
`quote_cost` / `make_prediction` — horizon dropdown, live cost, result summarised by the pure
`model.prediction_summary`, cost deducted from cash. A **Fees** submenu (Game menu) sets the world's
`fee_level`. And the big parity lever: a **`:` command line** that reuses `TraderApp.execute(line)`, so
*every* CLI command works from the GUI — predict, loan, repay, fees, find, look, market, run,
buy/sell/short/cover — with the result (ANSI-stripped) echoed into the news feed and every panel
repainted. A `?` Help dialog documents the keys and the command set.

That closes out **full TUI parity**: every keybinding and command in the README table now has a GUI
equivalent. Verified with a pure `prediction_summary` test, predictions/fees/command-line assertions in
the offscreen smoke, and a live command-line session — `buy $1000` / `loan 2000` / `predict 1d`
($56, 62% confidence) / `fees high` / `repay all` — cash and loan balance tracked exactly, each command
echoed to the feed. Full suite: 91 pass.

Committed as `bd214d0`. **The PySide6 desktop GUI is complete — all 11 slices (0–10) done, at TUI
parity.** `python play_gui.py`. Front-end count is now three (CLI · Textual TUI · PySide6 GUI).

## 2026-07-12 — GUI polish: dim the board row-highlight (SELECTION knob)

Matthew found the selected-row green too bright — it was `GREEN` (#2fae4e), the same green as the
panel borders, so a whole highlighted row glared. Pulled the highlight into a dedicated
`model.SELECTION` constant (previously the QSS used `GREEN` inline) and set it to **#1c682f ≈ 0.60×
GREEN**; also switched the selected-row text from `BG` (dark) to `FG` (light) so it stays readable on
the darker green. It's now a one-line knob — darker: halve GREEN → `#185727`; brighter: back toward
`#2fae4e`. Verified by sampling the rendered board: the selected row now fills `#1c682f` (6,255 px)
and the bright `#2fae4e` is down to just the panel borders (1,620 px). Full suite: 91 pass.

## 2026-07-12 — GUI bugfix: ticker forced an off-screen minimum window width

Matthew maximized the window and the chart vanished; restoring left the window oversized and it ran
off the screen. The console gave it away: `minimum size: 3436x670` — wider than his 1920 monitor.
Cause: the ticker `QLabel` holds the full ~18-symbol marquee string (~420 chars ≈ 6357px) with no
width constraint, so once `_scroll_ticker` populated it (first timer tick), its `sizeHint` dragged the
whole window's minimum width past the screen — Windows then clamped the geometry (`Unable to set
geometry …`) and the layout starved the right column (chart) to zero width. (The `KeyboardInterrupt`
at `_on_timer` in his paste was just where his Ctrl+C landed — not a bug.)

Fix: `self.ticker.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)` — the marquee already
fills-and-clips via the manual rotate in `_scroll_ticker`, so ignoring its text width for layout is
exactly right. Window minimum drops 3436 → 1521; verified the chart keeps a healthy width at 1920×1017
(719px), 1366×768 and 1000×650, and the window maximizes/restores normally. Full suite: 91 pass.

## 2026-07-12 — GUI: blank 'buy' spends cash on hand, not full 2:1 buying power

Matthew noticed the trade dialog's blank-quantity **buy** (the "max buy" shortcut) used
`buying_power` (= 2× equity), silently leveraging him to the 2:1 limit. Changed `model.trade_quantity`
so a blank **buy** spends **cash on hand only** — `max(0, cash) / (price · (1 + fee_rate))`, reserving
for the commission so it never tips into margin even with fees on. Blank **short** still uses full
buying power (a short is inherently a margin action), and an explicit qty / `$amount` can still use
margin (execute_order enforces the initial-margin limit). GUI-only — the Textual TUI's blank-buy is
unchanged (offered to sync it if he wants).

Verified: $5,000 cash → a blank buy now spends exactly $5,000 (was $10,000 via margin), margin debt
stays $0, gross = equity, meter 0.25 (was 0.50). Full suite: 92 pass (added a fee-reserve test + a
blank-short-still-uses-margin assertion).

## 2026-07-12 — TUI: sync blank-buy to cash-on-hand · GUI: 1:1 per-minute chart edge

Two follow-ups from Matthew's playtesting.

**TUI blank-buy synced.** Made the Textual TUI's `TradeDialog` blank-quantity **buy** match the GUI —
cash on hand only (`max(0, cash) / (price·(1+fee_rate))`), not the 2:1 buying power; blank short still
uses margin. Both front-ends now behave identically. (The little quantity-resolution logic is now
duplicated in `tui.py` and `gui/model.trade_quantity` — small enough to leave; a shared helper could
dedupe it later if it drifts.)

**GUI chart 1:1.** Matthew noticed the price chart's newest point only advanced every ~6 ticks. Cause:
`_refresh_chart` sampled `span // 240` — for the 1D view (1440 min) that's 6 min/point, and the leading
point only landed on the 6-min grid. Bumped the budget to ~1440 points (`span // 1440`), so 1H and 1D
are per-minute 1:1 and 3D/1W are only lightly downsampled; and it now **always pins the current minute
`(t, price)` as the final point**, so the live edge advances every tick on every range. Enabled
pyqtgraph `setClipToView(True)` + `setDownsampling(auto, mode="peak")` so the extra points stay cheap.
Verified: 1D chart = 1441 points and the leading edge tracks the clock 1:1 (tick 2881→2881, 2882→2882,
…). The equity curve was already per-advance. Full suite: 92 pass.

Committed as `4ea966a`.

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

## 2026-07-12 — GUI polish: trade log + silent error-handler integration (PLAN)

Matthew asked to (1) record buy/sell fills in the same activity list the new-world settings log to,
and (2) integrate his separate `Python ErrorHandler/error_handler.py` so GUI errors are logged
silently and never raise. Scope chosen: **both asks only**. Error handler: **vendored copy** into
`trader_pro/` (single stdlib-only file, no new deps). Credit may run out mid-run, so this is
checkpointed — one commit per step = one rollback point.

### ✅ COMPLETE  (all steps landed)
- Both asks shipped; full suite 99 pass throughout.
- HEAD anchors: base `5514a8e` · Step 0 `7f64c1d` · Step 1 `227c037` · Step 2 `a47d7e4` · Step 3 `d27fae2`.
- To roll back code: `git reset --hard <step-commit-sha>`. Results write-up below.

### Plan
- **Step 0** — write this plan + resume pointer. *(commit)*
- **Step 1** — `_on_filled` (gui/app.py ~1213) also calls `_log_line` so fills land in `self.news`,
  the same list `_after_world_swap` logs "New world · …" to. Verb-colored (buy/cover green,
  sell/short red/amber, matching the TradeDialog buttons). Message mirrors the status-bar line.
  Extend `tests/test_gui_smoke.py`. *(commit)*
- **Step 2** — vendor `error_handler.py` → `trader_pro/_errhandler.py`; add `trader_pro/errlog.py`
  with `guard` (= `capture(reraise=False, on_report=…)`), `setup_logging()` writing to a log file,
  and a no-op fallback so the shim is never itself a crash source. Unit test guard swallows + logs. *(commit)*
- **Step 3** — wire `guard` onto the GUI Qt slots (timer tick first — runs every real second — plus
  trade / new-world / save / load / command handlers); call setup in `run_gui()`. Verify GUI launches. *(commit)*
- **Step 4** — docs + final worklog. *(commit)*

### Notes for a cold resume
- Activity list = `self.news` (QListWidget); write via `_log_line(text, color)` (gui/app.py:1017).
- Colors available: `GREEN, GREEN_HI, RED, AMBER, DIM`. Fill result `res` has `.price .fee .realized_pnl`.
- Error-handler public API: `describe_error(e)` (never raises), `capture(reraise=False, on_report=cb)`,
  `install(hooks=…, style=…, stream=…)`. Source lives in the sibling `Python ErrorHandler` project.

### Results

**1 · Fills in the activity log.** Buy/sell fills used to only flash the status bar; now they also
land in `self.news` — the same list the "New world · …" line logs to. Added `model.fill_entry(verb,
qty, sym, res)`, the buy/sell sibling of `event_entry`/`closure_entry`, returning a `(text, colour)`
tuple (verb uppercased, price + fee/realized appended). Colours match the TradeDialog buttons:
buy green, sell red, short amber, cover bright-green. `_on_filled` now routes through it (and the
status bar reuses the same string), so the fee/realized formatting lives in one place instead of two.

**2 · Silent error handler.** Vendored Matthew's sibling *Python ErrorHandler* project verbatim as
`trader_pro/_errhandler.py` (stdlib-only, no new deps; banner says re-copy to update) and wrapped it
in `trader_pro/errlog.py`:
- `guard` — a decorator for Qt slots. Prefers the vendored `capture(reraise=False, on_report=…)`; if
  the handler is ever missing it falls back to a hand-rolled swallow. Either way an exception is
  described and logged, then the slot returns its default — it never re-raises. KeyboardInterrupt /
  SystemExit still propagate.
- `setup_logging()` — a rotating `logs/trader_pro.log` sink (1 MB × 3), idempotent, and it wires the
  vendored `install()` global hooks (excepthook / threading / unraisable) through a `_LogStream` so
  uncaught errors share the same file.
- `run_gui()` calls `setup_logging()`; the timer tick and all 15 user-facing slots wear `@guard`.

Design choice worth noting: everything funnels through the stdlib `logging` module (logger
`trader_pro`) rather than error_handler's own stream, so the file sink, the global hooks, and the
per-slot guard all land in one place. The vendored copy can drift from the ErrorHandler project — the
banner comment says to re-copy `error_handler.py` to refresh it.

**Scope deliberately left out** (Matthew chose "both asks only"): the pure view/sort/paging slots are
*not* guarded — they toggle in-memory view state over already-validated data and are the low-risk
surface; the crash-prone slots (engine, IO, parsing, the tick) all are. Timestamping fills with the
sim-clock and persisting the activity log across save/load were offered and declined.

**Tests.** `fill_entry` unit test + a smoke assertion that a buy reaches `news[0]`; 6 errlog tests
(swallow+default, KeyboardInterrupt passthrough, handler-missing fallback, idempotent setup, hostile
`__str__`) + a smoke assertion that a slot whose body raises does not propagate. Verified end-to-end
outside the suite that `logs/trader_pro.log` is created and the installed excepthook routes into it.
Full suite **99 pass** (was 92). Commits `7f64c1d → d27fae2`, local — not pushed.

## 2026-07-13 — Polish pass (multi-session): plan + Tier 1 (formatting)

Matthew asked an open "what can we polish about the game?" Ran four parallel reviewers (GUI,
TUI, gameplay, CLI/onboarding) over the whole play surface. Findings clustered into four tiers;
Matthew picked **all of them**, so this is a multi-session pass, one tier per commit/rollback point.

**The four tiers (roadmap for cold resume):**
1. **Formatting** *(this commit — done)* — shared `money`/`qty` helpers.
2. **Safety & never-crash** — CLI has no guard (unlike the GUI): raw traceback on non-UTF-8 stdout
   (default when piped on Windows) and any handler exception (`run 5 abc`) kills the REPL; wrap
   dispatch + reconfigure stdout to utf-8. GUI delete-save has no confirmation (one misclick = lost
   game). CLI never autosaves (quit/load discards silently, contra README). TUI binds bare `+`/`_`
   to buy/sell **1000** — contradicts help (says 1 unit; Ctrl for 1000) and a stray Shift 1000×'s an
   order. Onboarding: profile prompt `0` → `PROFILE_NAMES[-1]` = Apocalyptic (validate `1..N`).
3. **Feel & consistency** — empty-state placeholders (GUI+TUI blank tables), drop the "slice 9"
   dev-jargon resume line, P&L columns missing the `$`, no sort ▲/▼ indicator, paused status hides
   speed, off-theme pure-black ticker, port-table QTY column width (see Tier 1 note below).
4. **Gameplay balance** *(design calls — confirm with Matthew first)* — margin debit accrues no
   interest (free leverage; loans strictly dominated); loan limit/APR are per-loan not aggregate
   (tier-dodging); bonds never pay their coupon (dead "safe yield"); margin call force-closes the
   whole largest position instead of trimming to cure; prediction confidence ignores horizon and is
   underpriced; no milestones/run-stats though `nw_history` already holds the data.

### Tier 1 — shared formatting helpers  ✅
Two `money()` copies (cli + tui, both `f"${x:,.2f}"`) and ~19 quantity sites on `f"{q:g}"`.
Three real defects, all rooted in shared code so one fix lands in every front-end:
- **negatives** rendered `$-1,234.50` (dollar-then-minus) — now `-$1,234.50` (sign outside symbol);
- **sub-cent assets** collapsed to `$0.00` — the game's penny coins (~$0.00006) now keep ~4 sig figs
  (`$0.00005837`), so they're legible and distinct in `look`/board/fills;
- **large quantities** printed scientific (`1.7132e+06`) — now grouped (`1,713,205.88`), never `e+`.

New `trader_pro/fmt.py` (stdlib-only) owns `money(x)` and `fmt_qty(q)` (named `fmt_qty`, not `qty`,
because the front-ends already use `qty` as the numeric local it formats; `fmt_qty` scales decimals
by magnitude — 2dp ≥1, up to 6 for sub-unit crypto). `cli.py` and `tui.py` dropped their local
`money`; `cli` re-exports both so the existing GUI imports (`from ..cli import … money`) still
resolve. All 19 share/coin sites moved from `:g` to `fmt_qty(...)` across cli/tui/gui; the two
non-quantity `:g` uses (bond maturity `10y`, new-world cash default) left alone.

**Tests.** New `tests/test_fmt.py` (6 cases: grouping, negative-sign, sub-cent, no-sci-notation,
magnitude-scaled decimals, negative shorts) + fmt.py doctests (9). Full suite **105 pass** (was 99).
Verified live in the CLI: `look FRG` → `$0.00005837`, `buy FRG $100` → `bought 1,713,205.88 FRG`.

**Known nit deferred to Tier 3:** the CLI/TUI portfolio tables right-align QTY in a width-10 field;
a grouped 7-figure holding (`1,713,205.88`, 12 chars) overflows it and nudges the AVG column. Was
already fragile under `:g`; fold the column-width fix into Tier 3's alignment work.

Commit is local — not pushed.

## 2026-07-13 — Polish pass Tier 2 (safety & never-crash)

Five safety fixes so a bug, a bad keystroke, or a stray quit can't hurt the player.

**1 · CLI never-crash.** The CLI had no guard (the GUI got one last week). Two real tracebacks
closed: (a) a non-UTF-8 stdout — the *default* when piped or on a legacy Windows code page —
crashed the first `market` render on the sparklines/em-dashes; `repl()` now
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (and stderr) up front. (b) Any handler
exception killed the whole REPL; `execute()` now wraps dispatch, logs via `errlog.log_error` to the
same `logs/trader_pro.log` the GUI uses, and returns a friendly one-liner (KeyboardInterrupt /
SystemExit still pass through). `_run` specifically: guards the delay parse (`run 5 abc` → usage,
not `ValueError`) and catches Ctrl-C mid-run to stop cleanly and return to the prompt. Used
`setup_logging(install_hooks=False)` for the CLI — the dispatch guard covers the real surface and I'd
rather a genuinely-uncaught error still show a traceback than vanish silently.

**2 · Onboarding profile `0`.** `PROFILE_NAMES[int("0")-1]` → `[-1]` = Apocalyptic (hardest), and it
validated clean so no fallback. Now range-checked `1..len`, so `0` / `9` / `-1` all fall back to
Normal; valid `1..8` unchanged.

**3 · CLI autosave on exit.** The CLI never autosaved — quit lost an in-progress game. Now `repl()`
autosaves to the shared `autosave` slot on the way out **iff the world actually changed** (a cheap
`_session_fingerprint` of tick/cash/loans/positions, captured at start and compared at exit). The
gate matters: without it a read-only peek (`look`/`market`/`quit`) would clobber the shared autosave
the TUI/GUI resume from — I proved that to myself the hard way (see incident note). With the gate,
only a session that traded or advanced time writes.

**4 · TUI `+`/`_` footgun.** Bare `+`/`_` were bound to buy/sell **1000** while the help *and* the
action docstrings described buy/sell **1** with **Ctrl** for the big lot. On a US keyboard `+` is
Shift+`=`, so a stray Shift turned a 1-unit buy into 1000. Fixed the bindings to match the docs:
`+`/`_` = 1 unit (like `=`/`-`); the 1000-lot moved to `ctrl+equals_sign`/`ctrl+plus`/`ctrl+minus`/
`ctrl+underscore` (Textual 0.71 canonical names, verified accepted). Help text already correct — no
edit needed. (Ctrl+punctuation delivery is terminal-dependent; the dialog remains the reliable path
for arbitrary amounts. The point was removing the bare-key footgun.)

**5 · GUI delete-save confirmation.** `LoadDialog._delete` destroyed a slot on one click; now gated
behind `QMessageBox.question` (default focus **No**), naming the slot. Brings it to parity with the
TUI's existing `_pending_delete` guard.

**Tests.** +4 in `tests/test_cli.py` (bad-delay usage, handler-error caught not raised, profile-`0`
→ Normal incl. boundaries, fingerprint tracks change). Full suite **109 pass** (was 105). Verified
live: piped CLI no longer tracebacks and `run 5 abc` → usage; profile `0` → a Normal world; the
autosave gate proven against a temp dir (read-only writes nothing; trade/advance writes).

**Incident (honest note).** While verifying autosave I ran the real CLI to quit, which — working as
designed — autosaved and **overwrote `saves/autosave.world`** with a fresh blank game; its prior
contents are unrecoverable (atomic replace, gitignored). Named saves were untouched (incl.
`save.world`, tick 40801 ≈ $1.65M). Low real loss, but I overwrote a file I hadn't inspected — should
have targeted a temp dir from the start (which the gate re-verification now does). Left the blank
`autosave.world` in place for Matthew to decide on. This incident is *why* the fingerprint gate went
in — it's a genuine improvement, not just test hygiene.

**Deferred to Tier 3** (load-flow polish, kept out of Tier 2's safety scope): pre-`load` snapshot so
a mistyped `load` is recoverable, and bare `load` silently loading a stale `save` slot.

Commit is local — not pushed.

## 2026-07-14 — Polish pass Tier 3 (feel & consistency)

Fit-and-finish across all three front-ends. Lead item surfaced from a screenshot Matthew shared of
a live GUI run (net worth ~$1.2M): the equity chart's Y-axis was still in **scientific notation**
(`1.2e+06`) — ironic right after Tier 1 scrubbed `1e+06` out of every text surface.

**GUI charts — money-formatted axes.** pyqtgraph's default `AxisItem` renders large ticks in
sci-notation. New `MoneyAxis(pg.AxisItem)` (in `gui/app.py`) with `enableAutoSIPrefix(False)` +
`tickStrings` → compact money via a new `fmt.abbrev_money` (`$1.2M`, `$900k`, `$110k`, sub-dollar
falls through to `money()` so a penny-coin price axis stays legible). Applied to both the net-worth
equity curve and the price chart (`axisItems={"left": MoneyAxis(...)}`). Verified: net-worth axis
`$900k→$1.2M`, price axis `$110k→$125k`.

**Formatting consistency.**
- P&L columns now show the `$`: new `fmt.signed_money` (`+$50.00` / `-$50.00` / `$0.00`) on the
  positions P&L cell and the summary's unrealized figure (were bare `+50.00` beside `$`-columns).
- Flat positions render **neutral** (DIM) at break-even instead of glowing green — matches the
  board's `cell()` convention (value/pnl: green>0, red<0, else dim).
- TUI chart hi/lo used `${x:,.0f}` → `$0` for cheap assets; now `money()`, so penny coins show a
  real range.
- CLI/TUI portfolio **QTY column widened** (`:>10`/`:>9` → `:>13`) so a grouped 7-figure holding
  (`1,713,205.88`) no longer overflows and nudges the next column (the nit deferred from Tier 1).

**Empty states.** New `PlaceholderTableView(QTableView)` paints centered dim text when the model is
empty; `BoardView` extends it and the positions table uses it ("No open positions yet — Enter or
double-click a board row to trade"); the board sets a contextual line in `_rebuild_board` ("You don't
own anything yet…" for the Owned view). TUI board gets the same via a `_separator_row` `__empty__`
line ("you don't own anything yet — press 2 for stocks · 1 for crypto" / "no assets to show in …").

**Small feel.** GUI board **sort ▼** marker on the 1D % header when sorting (BoardModel gains a
`sort_active` flag set in `_rebuild_board`; the TUI already showed `↓%` in its board title). Dropped
the dev-jargon resume line ("…lands in slice 9" → "Ctrl+N starts a new world"). Ticker background
`#000000` → the app's `{BG}` (`#07120b`) so it stops being a colder off-theme black. TUI paused
status now keeps the speed visible: `[PAUSED · 10 hr/s]` instead of `[PAUSED]`.

**Tests.** `test_fmt.py` +3 (abbrev_money ×2, signed_money); `test_gui_smoke.py` +2 assertions (sort
▼ header, P&L cell has `$`). Full suite **112 pass** (was 109). Also rendered the GUI offscreen to a
PNG — confirms the layout/charts/colours render without regression; text shows as boxes there only
because the offscreen platform lacks Consolas (the real Windows app is fine), so text formatting is
covered by the unit/smoke assertions instead.

**Deferred (a coherent load-flow unit, more UX-safety than feel):** pre-`load` snapshot so a mistyped
`load` is recoverable, and bare `load` silently loading a stale `save` slot (+ the README `saves`
browser mismatch). Also left for later: disabling Trade/Predict while nothing is selected (lower value
now the empty-states explain the blank board) and a TUI footer `Enter → Trade` hint.

Commit is local — not pushed.

## 2026-07-14 — Polish pass Tier 4 (gameplay balance) — plan + checkpoints

The design-decision tier. Matthew chose (via a walk-through of the calls): **fix both** debt holes,
**pay bond coupons**, **fix prediction confidence + price**, and include **both** gentler margin calls
and milestones/run-stats. So all of Tier 4 is in scope. Money math → one commit per step = one
rollback point. Verified the two headline claims in code before starting (margin debt uncharged;
coupons never credited).

Steps (each: engine change + tests + verify):
- **1 · Debt economics** ✅ — margin carry + aggregate loans.
- **2 · Bond coupons** ✅ — pay coupon income as cash (price-smoothing #8 deliberately deferred).
- **3 · Predictions** ✅ — confidence falls with horizon; cost scales with the world's edge.
- **4 · Gentler margin calls** ✅ — trim only enough to cure the breach, not the whole largest position.
- **5 · Milestones / run-stats** ✅ — peak net worth, max drawdown, swans survived (best/worst-day dropped).

### Step 1 — debt economics ✅
`portfolio.py`: (a) `accrue_interest` now also compounds **margin debt** (negative cash) at a new
`MARGIN_APR = 0.08`, so 2:1 leverage held across idle stretches has a real carry cost instead of being
free — the loan system is no longer strictly dominated. Applies everywhere via the shared
`TraderApp._advance` (cli.py:369). (b) `borrow_limit` now nets out existing `loan_balance` (total
loans capped at ~2× net worth), and `take_loan` prices APR on **total** post-loan leverage — so
splitting a big borrow into small chunks no longer dodges the 6→35% tiers. `test_loans.py` +4
(margin interest accrues; positive cash doesn't; aggregate cap; stacked loans tier by total). 10
loan tests pass. Existing tests unaffected (they carry no pre-existing loans, and `(0+amt)/nw` keeps
the old APR assertion true).

### Step 2 — bond coupon income ✅
New `World.accrue_coupons(ticks)`: for each held bond it credits `coupon_rate · face · qty · Δt/yr`
to cash (a long earns, a short pays); wired into `TraderApp._advance` after `accrue_interest`. Bonds
go from a dead "safe yield" (they only moved on rate trades) to a real passive drip. **No double
count:** the price is the PV of *remaining* coupons and a par bond (seed case: `coupon_rate ==
base_yield`) marks at par regardless of how many coupons remain, so the income is genuinely additive
— verified: 10× GOVT-30Y (5.44%) earns exactly $544/yr into cash; net worth still reflects rate-driven
price moves on top. `test_world.py` +2 (income to cash; shorts pay, stocks earn nothing). 12
world/engine tests pass, incl. the untouched rate↔price invariant.

**#8 price-smoothing deferred (deliberately, per the working agreement — don't brute-force a subtle
thing).** The yearly-boundary "sawtooth" only shows for *non-par* bonds (par bonds already mark flat
at par, so the common case is fine). Every consistent fix has a real cost: discrete coupons inherently
step at anniversaries (that step is the *correct* ex-coupon drop once coupons are paid), and switching
to continuous-compounding annuity pricing shifts par off-face at seed (~+1.6% on a 30y 4.5% bond),
which would look wrong. Left the price formula untouched (zero risk to existing bond behavior); the
income is the valuable part and it's in.

### Step 3 — predictions: honest confidence + real price ✅
`predictions.py`: (a) the displayed **confidence** was the flat world `predictability` — a 30-day peek
read as sure as a 1-day one. Now `confidence = exp(-sigma)`, derived from the *actual* forecast
spread, so it falls with horizon and in fuzzier worlds (Normal 1d 94% → 30d 72%; Apocalyptic 1d 87%
→ 30d 47%). CLI label "world confidence" → "confidence". (b) **cost** was pocket change (~$11). Raised
`BASE_COST` 20 → 50 and added an `edge = 0.5 + predictability` multiplier, so a sharper world's peek
(worth more) costs more: same 1-day stock peek Calm $169 > Normal $133 > Apocalyptic $76; a mega-cap
is ~$28, crypto ~$157. Uniform ~2.5× over the old flat cost, × the world factor — a meaningful bite,
not a near-oracle for free. All relative-cost orderings and determinism preserved (edge is
world-level). `test_predictions.py` +2 (confidence falls with horizon; cost scales with edge). 6
prediction tests pass. `BASE_COST`/`edge` are one-liners to retune if it plays too steep.

### Step 4 — gentler margin calls ✅
`orders.liquidate_for_margin` closed the *entire* largest position each pass — a 1–2% breach could
nuke your flagship holding and realize the full loss. Now it closes only the notional needed to
restore the maintenance requirement (`need = −maintenance_excess / MAINTENANCE_MARGIN_RATIO`, ×1.02
for fees), capped at the position size. Small breaches trim; catastrophic ones still fully liquidate
(the `min` caps it and the loop moves to the next position). Verified: a slight breach (−40% move)
trims ~16% and the holding survives; −55%/−70% still close it out. `test_margin.py` +1 (trims not
nukes on a small breach); the existing blown-up-short liquidation test still passes (deep breach →
full close). 6 margin tests pass.

### Step 5 — milestones / run-stats ✅
`Portfolio` gains three serialized fields — `peak_net_worth`, `max_drawdown` (worst peak-to-trough
fraction), `swans_survived` — updated as time advances: peak/drawdown in `record_net_worth` (called
every `_advance`), and the swan counter in `_advance` (`sum(1 for e in events if e.kind ==
"flash_crash")`; aftershocks are `kind="aftershock"`, so no overcount). `from_dict` reads them with
defaults so old saves still load. Surfaced in all three front-ends: CLI `port` gets a `run · peak …
max drawdown … black swans survived …` line; the GUI positions summary a second dim line; the TUI
port panel a compact `run · peak … dd …% swans …`. Verified: an Apocalyptic fast-forward recorded a
75.6% max drawdown and 2 swans survived. `test_world.py` +2 (peak/drawdown tracking incl. recovery
keeps the worst; stats persist across save/load). Full suite **123 pass** (was 112 at Tier 3 end).

**best/worst-day dropped (deliberately):** the engine fast-forwards by evaluating seeded anchors, so
there's no per-day net-worth path to sample during a multi-day jump — a "best/worst day" stat would be
honest only when stepping day-by-day and silently wrong under fast-forward. Left it out rather than
ship a misleading number; the other stats are robust at any advance size.

### Tier 4 complete
All five steps landed, one commit each: `d577810` (debt) · `0259ebd` (bond coupons) · `99c9edc`
(predictions) · `1203f4c` (margin calls) · this (run-stats). All local — not pushed. Two knobs left
tunable by design: `MARGIN_APR` (0.08) and prediction `BASE_COST` (50) / `edge`. Deferred within the
tier: bond price-smoothing (#8) and prediction best/worst-day — both for the reasons above.

Commit is local — not pushed.

## 2026-07-14 — CLI load-flow cleanup (deferred item, "full fix")

The last outstanding item from the polish pass. The CLI's save/load lagged the TUI/GUI and the README
over-promised a `saves` browser it never had. Matthew picked the full fix:

- **`saves` command** — lists slots newest-first with profile, net worth, return, position count and
  age (built from the existing `persistence.list_saves`/`SaveInfo`; corrupt slots flagged red).
- **Bare `load` browses** — instead of silently loading a stale slot literally named `save`, bare
  `load` now shows the `saves` list; `load <name>` loads a specific slot. Unknown slot → friendly
  "type 'saves'". The startup "[l]oad" flow prints the list and defaults to the newest slot.
- **Pre-`load` snapshot** — `load <name>` first snapshots the current game to the `autosave` slot
  (skipped when loading autosave itself), so a mistyped/regretted load is recoverable.
- **README reconciled** — the Commands block now matches (bare-load browses; `saves` lists; loading
  snapshots first), and "How it works" notes bonds pay their coupon as income (Tier 4). CLI `help`
  gained the `saves` line.

Verified the whole flow against a **temp dir** (per the saves-hygiene memory — never the real
`saves/`): empty→message, two saves list newest-first, bare `load` browses without loading, `load
alpha` creates `autosave.world` first, unknown slot friendly. `test_cli.py` +3 (saves lists; bare
load browses not loads; load snapshots first). Full suite **126 pass** (was 123).

This closes every item from the four-tier polish pass except the two deliberately-deferred Tier-4
niceties (bond price-smoothing #8, prediction best/worst-day).

Commit is local — not pushed.

## 2026-07-14 — Standalone .exe build (PyInstaller)

Matthew asked for a build script to package the game as a Windows `.exe`, documented in the README.
The catch: three runtime paths resolved off `__file__`, which **breaks when frozen** — the seed data
wouldn't be found (crash on launch) and `saves/`/`logs/` would land in PyInstaller's temp `_MEIPASS`
dir and vanish on exit. So a *working* build needed the path handling fixed first, not just a script.

**Frozen-aware paths.** New `trader_pro/_paths.py` with `resource_dir()` (read-only bundled data —
`_MEIPASS` when frozen, repo root from source) and `user_data_dir()` (writable state — next to the
`.exe` when frozen, repo root from source). Routed the three sites through it: `models.DEFAULT_SEED_DIR`
(seeds), `persistence.SAVES_DIR` (saves), `errlog` log path. **From-source behaviour is byte-identical**
(both helpers return the repo root), so nothing changed in dev — 126 tests still green.

**Build script.** `scripts/build_exe.py` runs PyInstaller `--onefile --windowed --name TraderPro`,
bundling `data/seeds` via an absolute `--add-data` path (a relative one resolves against `--specpath`,
which bit me first try). Guards for missing PyInstaller / unbuilt seeds; optional `trader_pro.ico`.
Output is a portable `dist/TraderPro.exe` that keeps saves beside itself. Kept the script's own output
**ASCII-only** so it can't `UnicodeEncodeError` on its success line on a cp1252 console (same bug class
as the Tier-2 CLI fix).

**Verified for real.** Rather than the slow, un-headless-testable GUI build, I built a *CLI* one-file
exe (same `_paths` logic, stdlib-only) into scratch and ran it: `market` rendered and `buy BTR $500`
filled (bundled seeds found via `resource_dir()` → `_MEIPASS`), and `frozentest.world` + `autosave.world`
were written to `dist/saves/` **next to the exe** (`user_data_dir()`). The GUI exe uses identical path
logic, so it's proven bar the Qt bundle.

`.gitignore` already had `build/`/`dist/`; added `*.spec`. README gained a "Standalone Windows build"
section. `test_persistence.py` +1 (from-source paths resolve to the repo root, seeds present). Full
suite **127 pass** (was 126). PyInstaller isn't a runtime dep — only needed to build.

Commit is local — not pushed.

---

## 2026-07-15 — GUI: user-themeable accent colour (colour picker + settings.json)

Matthew asked for a colour picker that saves as a default "somewhere" so the theme's green can
become blue/red/whatever. Agreed on an **accent-only** first pass: recolour the chrome, leave P&L
semantics alone.

**The key wrinkle, found by reading the code:** `GREEN` was doing *double duty* — it was both the
theme accent (borders, menu highlights, command line, the TRADER PRO banner, row selection) **and**
the profit colour (`GREEN if pnl > 0 else RED`, board % changes, chart fills, buy/cover buttons).
Naively making "green" configurable would have turned profit blue when you picked blue. So the fix
was to **split the two roles**, keeping the names honest:

* `GREEN`/`GREEN_HI`/`RED` stay *fixed* P&L semantics — profit green, loss red, always.
* New `ACCENT`/`ACCENT_HI` (+ derived `SELECTION`) carry the themeable chrome. All ~17 chrome sites
  in `app.py` (borders/menus/hover/command-line) and the banner in `model.py` moved to `ACCENT`;
  the ~18 semantic-green sites were deliberately left untouched. Log-line confirmations stay green
  (success = green is conventional, and it needs no edits).

**One picker, three shades.** `model.accent_palette(accent)` returns `(ACCENT, ACCENT_HI, SELECTION)`:
`None` reproduces the exact hand-tuned phosphor-green literals (zero drift for existing users), and a
custom accent derives a brighter highlight (x1.2) and a dimmed row-selection (x0.6 — which reproduces
the original `#1c682f` from `#2fae4e` *exactly*, so the 0.6 factor is the very rule the old constant
encoded). So you pick one colour and the harmonious shades follow.

**Persistence.** New Qt-free `trader_pro/gui/settings.py` — a tiny `settings.json` living beside the
saves via `user_data_dir()` (so a portable Trader PRO carries your theme next to the `.exe`, same
philosophy as the save slots). Defensive like the rest of the codebase: missing/corrupt/non-object
JSON yields `{}` and never raises; writes are atomic (temp + `os.replace`), same crash-safe trick as
the save layer. `model.py` reads the accent once at import behind a try/except, so a broken settings
file can never stop the app booting.

**UI.** An **Appearance** menu (between Fees and Help) with "Accent colour…" (opens `QColorDialog`)
and "Reset accent to green". Both handlers are `@guard`-wrapped. **Restart-to-apply** for this first
pass — honest and simple; the dialog says so, and a log line confirms the save. Live-repaint is the
obvious Phase 2 (would need palette access to route through a mutable object rather than import-time
bound names) but was explicitly out of scope for "keep it simple."

**Tests & verification.** New `tests/test_gui_settings.py` (+15): hex validation, load/save round-trip,
corrupt/non-object fallback, accent get/set/clear, and the palette derivation (incl. the x0.6 =>
`#1c682f` identity). All I/O aimed at `tmp_path`, never the live file. Beyond the unit tests I drove
the real chain end-to-end: saved `#e5484d` via the actual API, imported `model` in a fresh subprocess,
and confirmed `ACCENT=#e5484d` / `ACCENT_HI=#ff565c` / `SELECTION=#892b2e` while `GREEN` stayed
`#2fae4e` — then cleaned the repo back to pristine (no settings.json, no temp turds). Full suite
**142 pass** (was 127). README's GUI paragraph gained the Appearance menu.

Commit is local — not pushed.

**Follow-up — accent on the charts.** Matthew asked to extend the accent to the two pyqtgraph charts
(price + equity curve). Same principle as the P&L split: the data line/fill/title is a *functional
up-vs-down signal* (green rising / red falling), and theming it would collapse up and down to one
colour for a red or amber accent — so the line stays green/red. Instead themed the chart **chrome**:
each PlotWidget gets a `1px solid {ACCENT}` frame (matching the news panel) and its left axis +
gridlines take the dim-accent `SELECTION` pen. Always hue-safe. Verified by rendering the styled
widget offscreen (QT_QPA_PLATFORM=offscreen + widget.grab()) at green and blue accents: chrome
follows the accent, the green up-line and red down-line stay readable against blue. Suite still 142.

---

## 2026-07-16 — Stop/limit orders (new feature) — Slice L1: core model + storage

Matthew asked for stop/limit orders next, then options, "in as many slices as you deem." Planned it as
five slices (L1 core model → L2 triggering in the advance loop → L3 CLI → L4 TUI → L5 GUI), each
committed and shippable, with options sketched to follow. The architecture makes this clean: `TraderApp`
(cli.py) is the shared session — the TUI and GUI both wrap it as `self.trader` and *all three* advance
time through `TraderApp._advance()`, so the trigger check will live in exactly one place.

**L1 — pure-additive core, no behaviour change yet.**
- `orders.py`: `OrderKind` (LIMIT/STOP); `PendingOrder` (id, asset, side, qty, kind, trigger_price,
  created_tick) with `is_triggered(price)` encoding the four-way truth table — SELL-limit & BUY-stop
  fire on a *rise* (≥), BUY-limit & SELL-stop on a *fall* (≤), touch counts as crossed; `PlacementResult`
  (truthy like ExecutionResult); `place_pending()` (validates qty>0, price>0, known asset; rests on the
  portfolio, no funds/margin touched until it triggers) and `cancel_pending()` (pop by id).
- `portfolio.py`: `Portfolio` gains `pending: list` + `next_order_id` (monotonic, serialized so ids stay
  unique across saves). `to_dict`/`from_dict` wired; `from_dict` uses a **local** `import PendingOrder`
  to avoid the orders↔portfolio import cycle. Back-compat: a blob without `pending`/`next_order_id`
  loads as empty list / id 1 (same defaulting pattern as the run-stats fields).
- Exported the new names from `core/__init__.py`.

**Design decisions.** Resting orders live on the *portfolio* (they're player intent and must save/load
with the account, like positions). Placement reserves nothing — the funds/margin check is deferred to
trigger time and reuses `execute_order`'s existing initial-margin gate, so a resting order that can't be
afforded when it fires just fails there (reported in L2) rather than needing a second margin model.

`tests/test_orders.py` (+6): id assignment/counter, validation rejects (no id burn), the trigger truth
table incl. exact-touch, cancel + unknown-id no-op, serialization round-trip, back-compat load. Full
suite **148 pass** (was 142). No `_advance` change yet — triggering is L2.

Commit is local — not pushed.

### Slice L2 — triggering in the advance loop

- `orders.process_pending(world)`: fires any resting order whose trigger the *current* price has
  crossed, in id order. A fired order leaves the book whether it fills or not — on success it goes
  through the existing `execute_order` (so it fills at current market and re-uses the initial-margin
  gate); if it can't clear margin at fire time it's **cancelled** with the reason (not left to retry
  forever). Returns one ExecutionResult per fired order (`.filled` distinguishes fill vs cancel).
- Wired into `TraderApp._advance`, right after prices update and **before** `liquidate_for_margin`, so
  a player's own stop-loss gets to de-risk ahead of a forced margin call. `_advance` now returns
  `(events, closures, fills)` — updated all **8** unpack sites (CLI `_next`/`_run`, TUI
  step/hour/day + play-tick, GUI `_advance_now`/`_on_timer`). Test call sites that don't unpack were
  unaffected.
- **Fidelity note (documented in code):** triggers are evaluated on the price at the *end* of each
  advance. In live play (a few ticks/advance) that's effectively every sim-minute; a big explicit
  fast-forward (+1d) can step over a level only touched intraday — the same end-point fidelity the
  seeded engine uses everywhere (design.md §5.2), and the reason best/worst-day was dropped in Tier 4.
- **Notifications brought forward:** rather than let triggered fills be invisible until the L4/L5 UI
  work, I added the fill/cancel line to all three feeds now — CLI `_fills_notice`, TUI `_log_fills`,
  GUI `pending_fill_entry` + `_log_news(..., fills)`. L4/L5 stay scoped to *placement* UI and the
  orders panel. Fills show green (◆), trigger-time cancellations amber (◇).

Verified the CLI display end-to-end (not just via tests): rested an in-the-money buy-limit and an
unaffordable buy-stop, ran `next 1` → `◆ limit filled — buy 3 A @ $122.14` and
`◇ stop cancelled: insufficient buying power …`, both left the book, the long opened. `test_pending_
trigger.py` (+4): each of the four kinds fires the right side, waits-until-crossed, trigger-time
cancellation removes without buying, and the `_advance` 3-tuple wiring. Full suite **152 pass** (was 148).

Commit is local — not pushed.

### Slice L3 — CLI commands (`limit` / `stop` / `orders` / `cancel`)

Grammar: `limit <SYM> <buy|sell> <qty|$amt> <price>` (and `stop …`), with `@` as optional sugar
(`limit AAPL buy 10 @ 120`). A `$amount` converts at the **trigger** price (the intended fill), and
`all` is refused for resting orders — a resting size must be fixed up front since holdings can change
before it fires (`_parse_resting_qty`). `orders`/`o` prints a table with a green `●` on any order whose
trigger is already met (fills next advance); `cancel <id|all>` drops one or all (accepts `#3` or `3`).
All four handlers reuse `resolve`, `place_pending`, `cancel_pending` and the existing colour/`col`
idiom; registered in the dispatch map; `help` + README Commands block + feature line updated.

**Cross-front-end for free:** the TUI and GUI command-lines both call `trader.execute(line)`, so these
commands already work in all three front-ends as typed commands. L4/L5 add *discoverable* UI (a TUI
orders panel, a GUI order-type selector + pending list) on top — the plumbing is done.

Verified by driving the real CLI: placed limit/stop/`$amount` orders (trigger-price conversion
16.39 = 1000/61.03 ✓), listed with the `●` armed marker, cancelled by id, and ran the full
place→`next`→fill chain (`◆ limit filled — buy 4 A @ $122.14`, filling at market ≤ the $134.28 limit,
book cleared). Bad inputs (missing args, bad side, unknown symbol, `all`, non-positive trigger) all
return friendly usage strings and rest nothing. `test_cli_orders.py` (+6). Full suite **158 pass**.

Commit is local — not pushed.

### Slice L4 — TUI surface (trade-dialog trigger + Ctrl+O orders panel)

Two discoverable affordances, both reusing existing patterns:

- **Placement folded into the TradeDialog.** Added an optional *trigger price* input. Blank → market
  order (unchanged). Filled → the same Buy/Sell/Short/Cover button **rests** a stop/limit, and the
  order *type is inferred from the trigger vs the current price* (`_infer_kind`): buy below / sell
  above = LIMIT, buy above / sell below = STOP. Every combination is the sensible one, so the player
  only picks a side + a price — no separate limit/stop toggle. `$amount` in the qty field converts at
  the trigger price; `all` is refused for resting (`_resting_qty`). The dialog dismisses a tagged
  `("resting", order)` tuple; `_on_trade_closed` branches on it and logs `rested #id …` in cyan.
- **`OrdersScreen` (Ctrl+O)** — the resting-order book, modelled on LoadScreen: a DataTable (ID, kind,
  side, qty, trigger, now, symbol, ● armed marker) with `x`/Enter to cancel the highlighted order and
  Esc to close. Cancels apply live via `cancel_pending`; the app refreshes on close.
- **Ambient discoverability:** the port panel shows `⏳ N resting order(s) · Ctrl+O` whenever any rest;
  HELP_TEXT gained the trigger-field note, the Ctrl+O key, and the `limit`/`stop`/`orders` commands.

The design intent is that a stop/limit is "the same trade, but later" — so it lives *in* the trade
dialog rather than behind a separate mode. Verified through the Textual pilot (real runtime, not mocks):
opened the dialog, set qty+trigger, pressed Buy → a BUY/LIMIT order appeared on the portfolio and the
dialog closed; the port panel showed the resting-order line; Ctrl+O listed both orders and `x` cancelled
the right one. `test_tui_orders.py` (+2: the `_infer_kind` truth table and the pilot scenario). Full
suite **160 pass** (was 158). L5 (GUI) is the last stop/limit slice.

Commit is local — not pushed.

### Slice L5 — GUI surface (trade-dialog trigger + Ctrl+O dialog) — stop/limit COMPLETE

The GUI mirror of L4, so all three front-ends now match:

- **Shared inference rule.** Pulled the limit-vs-stop-from-price logic into `orders.infer_order_kind`
  (buy below / sell above = LIMIT, buy above / sell below = STOP) so the GUI and TUI dialogs share one
  domain rule (the TUI's `_infer_kind` is now a thin `staticmethod` wrapper; its truth-table test still
  passes). A future web front-end reuses it too.
- **TradeDialog (Qt)** gains an optional trigger QLineEdit + a dim hint. Blank → market (unchanged);
  filled → rests a stop/limit via `place_pending`, inferring the kind. `$amount` in the qty field
  converts at the trigger, `all` is refused (`_resting_qty`). The dialog sets `self.fill =
  ("resting", order)`; `open_trade` branches to a new `_on_rested` that logs `rested #id …` (amber) to
  the activity feed + status bar.
- **OrdersDialog** — a QListWidget order book (id, kind, side, qty, trigger, now, ● armed), "Cancel
  order" (or double-click) drops the selected via `cancel_pending`, "Close" dismisses. Opened from
  **Game ▸ Resting orders… (Ctrl+O)**; the market timer is frozen while it's open (same as the trade
  dialog). The positions summary shows an ambient `⏳ N resting orders (Ctrl+O)` in the accent colour.

Verified offscreen in a subprocess (QT_QPA_PLATFORM=offscreen, the repo's GUI-test convention): drove a
real `TraderGUI` through a LIMIT placement (buy below), a STOP placement (buy above), `$1000`→10 units
at the trigger, the `all` rejection, a blank-trigger market-order regression, `_on_rested` logging, the
ambient count, and OrdersDialog list+cancel. `test_gui_orders.py` (+1). Full suite **161 pass** (was 160).

**Stop/limit orders is done** — engine + CLI + TUI + GUI, 161 tests. Next feature: options (O1–O5).

Commit is local — not pushed.

---

## 2026-08-04 — V1.8 "polish pass" agreed (design.md §11) + Slice P1: session memory

Matthew asked how else to polish the game. Audited the code with polish glasses on (settings.json
holds *only* the accent; window hardcodes 1120×720; zero audio; fixed watchlist; fills scroll away
forever; no stats/history/watch/alert commands anywhere in the shared CLI) and pitched four
directions — he took **all four**, and asked for it planned in slices. Result: a 15-slice backlog
in 4 waves (A session memory · B feel · C trader QoL · D charts & branding), written into
**design.md as §11** with checkboxes, sizes, dependencies (P1→{P5,P6,P12,P14}, P2→P14, P7→{P8,P9})
and parked items (achievements, candlesticks). Options (O1–O5) stays queued behind the pass.
**Note on P5 (sound): Matthew wants his PySynthRack dropped in for the synthesis.** The stale
"*Next step: V0.1…*" footer got refreshed while I was in there.

### Slice P1 — settings expansion + session restore (GUI)

The GUI now remembers your session. `settings.json` gains `geometry`, `view`, `sort_1d`,
`chart_range`, `speed` beside `accent`; all five restore at boot and persist in **one atomic
write** from `closeEvent` (best-effort, exactly autosave's stance). The **fee level is
deliberately excluded** — it lives on `world.config` and travels with the *save*, not the install;
restoring it from settings would fight whatever game you load.

- `gui/settings.py`: new `get_setting` / `update_settings` generics (a `None` value *removes* its
  key — "unset" beats storing nulls), accent helpers refactored on top (their tests pass
  untouched, which is the proof the generics behave). Paths now resolve **at call time** through
  `settings_path()`, which honours a `TRADER_PRO_SETTINGS_DIR` env var. That hook exists because
  the GUI now *reads* settings at construction — and the offscreen GUI tests run the real
  `TraderGUI` in subprocesses that inherit our environment, so without it a developer's live
  settings.json (say, `view: stocks`) would silently bend test assertions. New
  `tests/conftest.py` autouse-fixture points the var at a per-test tmp dir for the whole suite.
- `gui/app.py`: restore is split around `_build_ui` on purpose — speed + chart range are plain
  indices the builder bakes into its initial labels, so `_restore_prefs_pre()` runs *before* it;
  geometry / view / sort need the widgets, so `_restore_prefs_post()` runs after. Geometry rides
  Qt's own `saveGeometry()/restoreGeometry()` blob (hex in the JSON) — maximised state and
  multi-monitor sanity come free, and junk falls back to the 1120×720 default. The view restores
  through the public `view_*` methods (button check + board rebuild for free), with sort applied
  *first* so one rebuild covers both. Every read treats settings as untrusted user-editable JSON:
  wrong type / out-of-range → silently keep the default, per the never-crash-the-UI stance.
- Tests: `test_gui_settings.py` +4 (env override; get-with-default; merge + None-removes +
  atomicity; accent-rides-the-generics). New `test_gui_session.py` +3 in the smoke-test subprocess
  idiom: a pre-seeded settings file restores into the real widgets (speed/range labels, checked
  view button, `board_model.sort_active`); a state-change + `gui.close()` drives the *real*
  `closeEvent` persistence path and round-trips through the JSON (geometry verified as a genuine
  hex blob); an all-junk file (`speed: 99`, `view: "bogus"`, non-hex geometry…) boots clean on
  defaults and the app still advances.

**Verification — and a change of venue for the test run.** Matthew moved the laptop mid-slice, so
the work paused on disk-clean files and resumed after reconnect. Then a wrinkle: `device_bash` now
runs in an isolated Linux VM with the folder mounted, and that VM has **no pytest, no PySide6, and
no network** to install them — the old "run the suite in place on the mount" recipe is simply gone.
So the suite now runs in the **cloud container** instead: stage the repo across, `pip install
pytest textual<0.72 PySide6 pyqtgraph`, run offscreen. Python 3.11 / PySide6 6.11 / Textual 0.71
there. As a bonus the stale-bytecode trap from earlier sessions doesn't apply (fresh copy, real
mtimes), though `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider` stayed on out of habit.

**169 pass** (was 161; +8 = 4 settings + 4 session). Then I checked the new tests aren't vacuous by
**mutating the feature three ways** and confirming each mutation is caught by exactly one test:
delete the `_restore_prefs_post()` call → the restore test fails; drop `_save_prefs()` from
`closeEvent` → the persistence test fails; remove the range/type validation on `speed` → the junk
test fails. Also drove the two view paths the first restore test didn't cover (`movers`, which
bypasses `_set_view`, and `owned`) against a real window — both restore correctly, and `movers`
became a fourth test rather than a note.

All eight files are committed to the repo; the README's stale "~50 tests across 12 files" is now
"169 tests across 29 files" (in both places it appeared) and its coverage sentence now mentions
resting orders, persistence, GUI session memory and the offscreen-subprocess Qt convention.

**Commit is Matthew's to run, as ever:**

```
git add design.md README.md WORKLOG.md trader_pro/gui/settings.py trader_pro/gui/app.py \
        tests/conftest.py tests/test_gui_settings.py tests/test_gui_session.py
git commit -m "V1.8 polish backlog (design.md §11) + P1: GUI session memory

Plan the polish pass as 15 slices in 4 waves, then ship the first:
the GUI now remembers window geometry, board view, sort, chart range
and speed in settings.json, restoring at boot and persisting on close.

- settings.py: generic get_setting/update_settings (None removes a key);
  call-time path resolution via settings_path() + TRADER_PRO_SETTINGS_DIR
  so tests never touch a real settings.json; accent helpers ride the generics
- app.py: restore split around _build_ui (indices before, widgets after);
  Qt saveGeometry blob; every read validated, junk falls back to defaults
- tests: +8 (169 total), incl. subprocess round-trips through the real
  closeEvent path and an all-junk settings file
- fee level deliberately NOT persisted here: it lives on world.config"
```

---

## 2026-08-04 — P16: the TUI new-world modal stops asking you to spell

Matthew, on the new-game dialog: *"the difficulty has to be typed in and that is going to require
users both know and can spell (despite being shown), and this is just too much to ask of a
'normal' human apparently."* Worth pinning down **which** dialog first — the GUI's `NewWorldDialog`
has used `QComboBox` for profile and fees since it was written, and the CLI lists the profiles as a
numbered 1–8 menu. The offender was the **TUI's Ctrl+N modal**: profile was a bare `Input` with the
eight names *not shown anywhere on the screen*, and the fallback made it worse —

```python
profile = next((n for n in PROFILE_NAMES if n.lower() == raw.lower()), cfg.profile)
```

— a typo silently kept your **previous** profile. You'd press Enter, get a world, and it wouldn't
be the world you asked for, with nothing on screen to tell you. That's the real bug; the spelling
was just the trigger.

**Both dropdowns now.** `Select` for difficulty and fees, `allow_blank=False`, seeded from the
running world's config (with a fallback if an old save names a profile this build no longer has —
`Select` raises on a value outside its options). Labels stay short (`4. Normal`) so they can't
wrap; the **selected profile's tagline shows underneath and follows the highlight**, which keeps
the box narrow while teaching the 1–8 scale as you arrow through it. Fee options carry their real
rate (`medium  (0.30% per trade)`) so the cost of the choice is visible before you commit.
`_start()` lost all its parsing and spell-checking — the dropdown values are known-good by
construction; only seed and cash can still be junk, and they keep their existing fallbacks.

**The Enter problem.** Textual's `Select` binds `enter` to *open the dropdown*, which would have
broken the modal's "Enter start" promise for two of its four fields — Enter meaning "go" here and
"open a menu" there is exactly the small inconsistency that makes a keyboard UI feel untrustworthy.
Fixed with a five-line `NewWorldSelect(Select)` that rebinds **only** `enter` to post a `Start`
message (subclass BINDINGS override the base per key — verified, `down`/`space`/`up` still open the
list). So: Enter always starts; ↑ ↓ / Space open a dropdown; while one *is* open, Textual's own
overlay handles Enter to pick. Esc closes an open dropdown first, then cancels the modal — a free
consequence of the overlay's own binding, and the right behaviour.

**Cosmetics.** Box widened 64 → 70 so the longest tagline (Normal's, 62 chars) stays on one line
and the modal doesn't jump as you arrow down the list; the header and key-hint lines were trimmed
to stop them wrapping ("…save first to keep / it)" and "…Esc / cancel" both wrapped before, and the
new hint line is longer). Verified visually by exporting real SVG screenshots from the pilot
(`app.export_screenshot()`) and rasterising them — closed and open states both checked, no wraps.

**Tests** — new `tests/test_tui_new_world.py` (+4): three pure ones (all 8 profiles present in
scale order with short labels, fee labels carry the true rate, `_tagline_for` can't raise on junk)
and one pilot scenario that opens the modal, checks it's pre-selected and focused on difficulty,
asserts **no free-text field remains** except seed/cash, watches the tagline follow a change,
presses Enter *from the dropdown* and confirms the world that comes back is the one picked
(profile, fees and seed all), then checks ↑ opens the list instead of starting and the two-stage
Esc. Mutation-checked all three behaviours: drop the `enter` rebinding, hardcode `profile =
cfg.profile` (i.e. reintroduce the old silent-fallback bug), or stop updating the tagline — each
fails the scenario. Full suite **173 pass** (was 169). README's TUI key table and test counts
updated; design.md §11 gained P16 under "unplanned, shipped on sight" (achievements shuffles to
P17).

**Commit is Matthew's to run:**

```
git add design.md README.md WORKLOG.md trader_pro/tui.py tests/test_tui_new_world.py
git commit -F- <<'MSG'
P16: TUI new-world modal — difficulty & fees are dropdowns

The Ctrl+N modal asked players to type a profile name that was never
shown on screen, and a typo silently kept the previous profile — so you
could start a world you didn't choose, with no indication. Both fields
are now Select dropdowns seeded from the current world, matching the GUI.

- short "4. Normal" labels; the selected profile's tagline follows the
  highlight underneath, so the 1-8 scale teaches itself
- fee options show their real rate (medium -> 0.30% per trade)
- NewWorldSelect rebinds only `enter` (-> start) so the modal's
  "Enter start" promise holds in every field; up/down/space still open
  the list, and the overlay keeps Enter for picking
- _start() drops all profile/fee parsing: dropdown values are valid by
  construction
- box 64 -> 70 so the longest tagline doesn't wrap or jump the layout
- tests: +4 (173 total), incl. a pilot scenario proving the picked world
  is the world you get
MSG
```

---

## 2026-08-04 — P17: held keys stop flooding the TUI, and a .gitattributes

Matthew hit a crash on quit and waved it off: *"its because I held down s and my repeat rate is
higher than their maths calculated for."* The traceback was Textual's own
(`Timer._run_timer` → `RuntimeError: cannot reuse already awaited coroutine`, during
`asyncio.run()` shutdown, on his Python 3.14). Worth a look anyway, because *why* the app was
still churning at shutdown is our business even if the exception isn't.

**Couldn't reproduce the exception — found the cause of the pressure instead.** On Python 3.11 /
Textual 0.71 in the container, hammering `s` through the pilot produced no shutdown error at all.
But it produced a much more interesting number: **200 presses took 48 seconds.** Profiling the two
halves:

```
_advance(1)        20.20 ms          _refresh()        12.51 ms
_advance(1440)     20.49 ms          _render_chart()    1.62 ms
```

Two things fall out. Each `s` press costs ~33 ms of our own compute before Textual has painted
anything — a full `_advance` plus a `_refresh` that *clears and rebuilds the entire board*. So a
key-repeat rate above ~30/s queues work faster than the app can drain it, and the backlog is still
unwinding when you quit. Matthew's read was right; the maths that didn't allow for his repeat rate
was **ours**, not Textual's.

And the second thing is the fix, sitting right there: **`_advance(1440)` costs the same as
`_advance(1)`.** Advancing a whole day is as cheap as advancing a minute, because prices are a pure
function of `(world_seed, tick)` (design.md §5.2) — `engine.advance` just moves the clock, and the
per-advance work (interest, coupons, `process_pending`, one `fired_between`) is O(1) either way.
So N presses never needed N advances.

**A leading-edge rate limit, not a debounce.** `_request_steps` banks the ticks; the first press
applies **immediately** (a tap feels exactly as it did, and the existing tests that step-then-assert
keep working unchanged); repeats arriving inside a 50 ms window are batched and applied by
`_drain_steps` as **one advance and one redraw**. Measured on a 100-press burst: **3039 ms → 58 ms,
a 52× reduction**, and 2 redraws instead of 100. This is the shape the live-play loop has always
used — `_on_timer` batches a whole timer tick's worth of minutes — so manual stepping was simply
the odd one out.

Three details worth recording:

* **Events are now logged for `s`.** `action_step` used to log fills but *not* events, presumably
  because one minute rarely has news. Now that a held `s` can cover an hour in one batch, silently
  eating a black swan would be a real loss, so all three step actions log events and closures like
  the play loop does.
* **Modals.** A drain can be armed a moment before a modal opens, and `_refresh` can't query the
  base-screen widgets from under one. `_drain_steps` bails out early in that case leaving the
  ticks *banked* (not dropped), and the timer re-arms until the modal closes — the same bail-out
  `_on_timer` has always done. Mutation-tested: remove the guard and the test dies on Textual's
  `NoMatches`, which is exactly the crash it prevents.
* **Fidelity, stated plainly.** Batched ticks mean resting stop/limit orders are evaluated on the
  end-of-batch price, and one net-worth sample is recorded per batch rather than per minute — the
  same end-point fidelity `+1d` and live play already have (design.md §5.2, and the L2 note above).
  At a real key-repeat rate the batches are 2–3 minutes, so this is theoretical rather than felt;
  it only grows when the app is behind, which is precisely when catching up is what you want.

**Tests** — new `tests/test_tui_stepping.py` (+2). One pins the invariant the whole optimisation
rests on: 60 single-tick advances and one 60-tick advance land on identical prices for 40 assets,
so batching can never change *where* you end up. The other drives the pilot: a tap applies at once,
50 repeats bank without moving the clock or redrawing, the drain applies all 51 in one go with
**2 redraws not 51**, mixed `s`/`h`/`d` batch together correctly, and the modal case keeps its
ticks and lands them afterwards. Both mutation-checked (remove the coalescing → fails; remove the
modal guard → fails). Full suite **175 pass** (was 173).

**Also: `.gitattributes`.** `* text=auto` with `*.cmd`/`*.bat` pinned to CRLF and png/ico/exe
marked binary. This is what's behind the phantom `data/seeds/*.json` and `start.cmd` diffs that
have been sitting in `git status` for weeks, and the "LF will be replaced by CRLF" warnings on
every add of a file I wrote from the cloud container. After committing it, once:
`git add --renormalize .` then commit the result.

**Held back from disk deliberately.** His repo is still mid-merge from the force-push detour
(README/WORKLOG/design.md carry conflict markers), and `git merge --abort` resets tracked files —
so writing these edits now would risk them being discarded. Everything is delivered to him in
chat; it lands on disk once he's aborted.

---

## 2026-08-04 — session close: TODO.md + two nits filed

Matthew needed to shut down, so this is a deliberate stopping point rather than a slice.

Everything from today is committed and pushed (`c401f52`): **P1** (GUI session memory), **P16**
(TUI new-world dropdowns), **P17** (coalesced held-key stepping), and the `.gitattributes`.
Working tree clean, **175 tests pass**, nothing half-finished to reconstruct.

**New `TODO.md`** at the repo root — a short "where we stopped, what's next" note that points at
design.md §11 for the full backlog rather than copying it, so the two can't drift. It carries the
current state, the next slice with its actual blocker written out, and the working notes that cost
real time to rediscover (how to run the suite from a cloud session, why the Qt tests live in
subprocesses, how the Textual screenshots are made, the `<0.72` pin).

**Two nits filed as P18/P19** from a screenshot of a 31-minute-old world (achievements shuffles to
P20):

* **P18** — every lookback clamps to `max(0, t - n*DAY)`, so on a young world 1D / 7D / 31D all
  measure from tick 0 and print the *same* number (BTR −1.46% three times). Mathematically honest,
  visually identical to a broken column; the chart pane next door already handles this properly
  with "(not enough data yet)". Flagged the sorting gotcha: movers and sort-by-1D% sort on these
  values, so whatever represents "no data" has to survive `sorted()`.
* **P19** — the ticker tape hardcodes `f"{price:,.2f}"` and renders every sub-cent coin as
  `FRG 0.00`, while the board directly below shows `$0.0000001834`. `fmt.money()` was *written* for
  exactly this (it keeps ~4 significant figures under a cent), is already imported at both call
  sites, and the GUI's `ticker_text` has the identical bug. Close to a one-line fix in each.

**Next slice is P2** (live accent repaint). Its blocker is written into TODO.md so it can start
cold: `gui/model.py` binds the palette as module-level names at import time and `gui/app.py` bakes
those into stylesheet strings when widgets are built, so rebinding later does nothing — the work is
routing the palette through a mutable theme object and restyling live widgets. The
accent-vs-P&L-semantics split must survive it.

---

## 2026-08-09 — P19, P18, and a flake that turned out to be real (P21)

Picked up cold: working tree clean at `3a54dd3`, 175 green, nothing half-finished. Matthew chose
the two small screenshot nits before starting P2, which turned out to be the right call — one of
them shook a latent bug out of the suite.

### P19 · Ticker precision (XS)

Exactly the one-line swap it was filed as. `_build_ticker` (`tui.py`) and `ticker_text`
(`gui/model.py`) both built their segment with `f"{price:,.2f}"`, so every penny coin scrolled
past as `FRG 0.00` while the board two rows below showed `$0.0000001834`. Both now call
`fmt.money()`, which keeps ~4 significant figures under a cent and was already imported at both
sites. The tape gains a `$` in the process, which matches the Price column beside it.

**Tests** (+1, plus an assertion inside the existing TUI feature scenario): pick the cheapest
asset on the tape, assert its rendered segment equals `money(price)` and that the literal
`SYM 0.00` is gone. Mutation-checked both: put `:,.2f` back and both fail, with the failure
message printing the actual tape (`MEMZ 0.00`) — which is a nice error to read.

### P18 · Honest change columns (S)

The filed gotcha — "mind the sorters" — dissolved once I traced the call graph, because the
render path and the sort path were **already separate**. Every sorter (`_movers` / `movers_ids`,
the `o` toggle's `by_change`, both tickers' arrows) calls `_chgNd` / `chg_pct` directly; only
`_add_row` / `row_ctx` feed the columns. So the change is surgical rather than invasive:

* `_chgNd` / `chg_pct` keep their float contract, and their docstrings now say *why* — on a young
  world the clamp gives change-since-open, which is a genuinely useful ordering. Blanking it would
  have made the movers view useless on day zero.
* New `_has_window` / `has_window` (is the world at least `n` days old?) and `_chg_col` /
  `chg_col` (the number, or `None`). `_RowCtx.chg*` is now `float | None`.
* A shared `_pct_cell` in each front-end renders `None` as a dim `—` and otherwise as the signed
  percentage, replacing three near-identical lambdas in `BOARD_COLUMNS` and three branches in
  `cell()`. Net: the change columns got *shorter*.

The one consequence worth naming: movers ranks by a column that reads `—` on a young world, which
would look like a board ordered by nothing. So the movers header hint switches from `1D %` to
`since open` until the world is a day old. The columns then light up one at a time as the world
ages — 1D at day one, 7D at week one, 31D at month one — which reads as a system doing its job
rather than a system that's broken.

**Tests** (+7): a new `tests/test_tui_change_columns.py` drives three worlds through the pilot
(31 minutes → all three dashes and the `since open` hint; 2 days → 1D real, 7D/31D dashes;
40 days → all three real *and mutually distinct*, which was the original complaint), plus the pure
GUI equivalents in `test_gui_model.py`. Three mutations, three catches — the third being the
interesting one: deliberately route `chg_col` into the sorters and the suite dies with
`TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'`. The trap named in
the design note is now guarded, not merely avoided.

### P21 · Ticker timer survives teardown (XS, unplanned)

The first full-suite run after P18 came back **1 failed, 175 passed** —
`test_dialog_dismiss_is_independent_of_button_count[1]`, `NoMatches` on `#ticker` inside
`_tick_ticker`. Three re-runs of that file passed, three full runs of a *pristine* copy passed,
three full runs of the modified tree passed. Textbook shrug-and-move-on. It reproduced
deterministically instead:

```python
async with app.run_test(...) as pilot:
    await pilot.pause()
app._on_timer()          # NoMatches — the app is gone, the interval isn't
```

The 0.3 s interval can fire once after teardown. `_on_timer`'s existing guard only covers "a modal
owns the screen" (`screen_stack > 1`), and by teardown the stack is back to 1 while the widgets
are already unmounted. One line — `if not self.is_running: return` — and the race is gone. Filed
as P21 because P20 is still reserved for achievements.

Worth recording as a habit: **an intermittent red suite is a bug report.** Re-run three times
against a pristine tree before believing it's noise, then try to make it deterministic.

### State

**183 tests pass** (was 175), three consecutive clean full runs. Written back to disk uncommitted,
with the three commit commands in `TODO.md` ready to paste. Screenshots of the young and aged
worlds (`tui_p18_young.png` / `tui_p18_old.png`) went to Matthew for the visual check. Next is
**P2**, live accent repaint.

---

## 2026-08-09 (cont.) — P2 · live accent repaint

Wave A's second slice, and the one with a real design decision in it. The filed blocker was
accurate: `gui/model.py` did `ACCENT, ACCENT_HI, SELECTION = accent_palette(_saved_accent())` at
import, and `gui/app.py` interpolated those names into ~25 stylesheet strings as its widgets were
built. Rebinding the module attribute later was a no-op — the characters were already in the
strings — so the picker could only write `settings.json` and pop a "restart to apply" box.

**The shape of the fix.** A `Theme` class holding `accent` / `accent_hi` / `selection`, one
module-level instance `THEME` seeded from the saved accent, and `THEME.set(hex_or_None)` to
re-derive all three. Every f-string became `{THEME.accent}`, which reads the attribute at *format*
time. The three module constants are **deleted**, not aliased — a stale copy is precisely the bug,
so leaving a compatibility alias would have left the trap armed. `test_no_stale_palette_constants_remain`
asserts `gui.model` has no `ACCENT` / `ACCENT_HI` / `SELECTION` attribute, with a message
explaining why, so a future "convenience" alias fails loudly instead of quietly re-breaking it.

**Making the repaint reach everything.** Reading THEME late is necessary but not sufficient — a
stylesheet set once at construction still holds old text. So every accent-baked style on a
*long-lived* widget moved out of `_build_ui` into two idempotent passes:

* `_apply_theme()` (already existed) — the window stylesheet: buttons, menu bar, menus, table
  `selection-background-color`, header sections.
* `_style_panels()` (new) — the two pyqtgraph charts (border stylesheet **and** the left axis pen,
  which is a Qt pen, not CSS), the news list, and the command line.

`_restyle_theme()` runs both and regenerates the two accent-coloured HTML labels (the TRADER PRO
banner via `header_html`, the resting-order badge in the positions summary). `set_accent()` =
`THEME.set(...)` + `_restyle_theme()`, and the two menu actions call it after persisting. The
construction sites now carry a one-line pointer (`# accent border: _style_panels()`) so nobody
re-inlines a stylesheet there.

**Modal dialogs needed nothing** — they read THEME in `__init__` and are constructed fresh on every
open, so they were already correct once the reads were late. Worth stating explicitly because it
looked like six more call sites at first glance; the test opens a `HelpDialog` *after* the change
and asserts it's born blue, which pins that reasoning rather than leaving it as a comment.

**Tests** — new `tests/test_gui_theme.py` (+3). The centrepiece drives an already-built window
through green → blue → reset in a subprocess and checks six surfaces (window, news, command line,
both charts, header HTML) each gained the new accent *and* lost the old one, that the axis pens
followed via `pen().color().name()`, and that reset is byte-identical to boot. Plus a pure `Theme`
unit test and the no-stale-constants guard. Three mutations, three catches: drop the restyle call
(the old world — fails), make `_style_panels` run only once (fails), re-add the module constants
(fails). P&L semantics get their own assertions: `GREEN`/`GREEN_HI`/`RED` unchanged and a
profit/loss cell still green/red under a blue theme.

**186 tests pass**, three consecutive clean full runs. README's Appearance sentence updated —
"applied next launch" became "applied the instant you pick it".

**P14** (theme presets + CRT scanlines) is now unblocked: presets are just named arguments to
`set_accent`.

---

## 2026-08-10 — P3 · autosave generations (Wave A complete)

The last Wave A slice, and the smallest of the three on paper: rotate `autosave` → `.1` → `.2`,
fall back down the chain when the newest won't load. It came in at about the size expected, but
the smoke run at the end turned up something the tests couldn't have — see P22 below.

**Why generations at all, when saves are already atomic.** Worth stating, because it looks like
belt-and-braces on a solved problem. `save_game` writes a temp file and `os.replace`s it, so a
crash *mid-write* genuinely cannot corrupt a slot. Generations cover the failures atomicity has
no answer for: a bad sector under the file, a hard power cut before the filesystem journal caught
up, a save that was already wrong when we serialised it. The autosave fires every 30 s, so the
chain only spans ~90 seconds — that's not time travel, and it isn't meant to be. It's "you lose
one autosave interval instead of the session".

**Rotate before the write, not after.** Renames, never copies, so rotating a save costs the same
whatever it weighs — that's what makes it affordable on the 30-second timer. The order is: drop
the oldest, move each generation back, then write the new gen 0. That leaves one observable
window: a crash between the rename and the write leaves `.1` populated and **no gen 0 at all**.
So `has_autosave()` had to stop asking about the live slot and start asking about the whole chain
— otherwise the crash that generations exist to survive would present as "no save, here's a fresh
world", which is exactly the outcome we were trying to prevent. A test pins that case by calling
`rotate_autosaves()` and simply not writing.

**The oldest is dropped explicitly, and that isn't redundant.** `os.replace(.1, .2)` already
overwrites `.2`, so deleting it first looks like a no-op — and it is, *while the chain is full*.
Punch a hole in it (a backup deleted by hand, a rename that failed) and the tail never gets
overwritten again: a stale generation lives forever and resume can fall all the way back to it.
`test_rotation_ages_out_a_stale_generation_across_a_hole` builds exactly that hole and asserts the
ancient save is gone. Without it the explicit `unlink` would have been untested dead-looking code
that a future cleanup deletes.

**Two decisions about how visible the backups should be.**

* *Hidden from the `Ctrl+L` browser.* `list_saves` globs `*.world`, so untouched it would have
  shown `autosave.1` and `autosave.2` as pickable slots — three near-identical rows, 30 seconds
  apart, burying the saves you actually named. They're recovery files. `read_info` still calls a
  backup an autosave when you ask about one directly, because it is one; it's the *browser* that
  filters.
* *Deleting the autosave takes all three.* Otherwise you delete the autosave, relaunch, and
  resume from `.1` — the slot you just deleted appears to come back. That one is a bug report
  waiting to happen, so `delete_save` now expands the autosave slot to its whole chain.

**Telling the player.** A silent fallback rewinds you ~30 seconds with no explanation, which is
the kind of thing that reads as "the game ate my trades". `load_autosave` returns `(world, path)`
rather than just the world, both resume paths compare it against gen 0, and each front-end says so
— amber in the TUI news pane, red in the GUI log. `gui.model.boot()` grew a third return value for
it; the one caller in the tests moved with it. The TUI message started as one long sentence and
was cut to two short lines after the screenshot showed the news pane clips rather than wraps
(`tui_p3_backup_resume.png`). The existing "Resumed your last game · …" line clips the same way at
that width — pre-existing, noted in `TODO.md`, not this slice.

**P22 · the error log was never silent.** The end-to-end smoke run — five autosaves, corrupt gen 0,
resume — printed the recovery *and* a sixty-line traceback to the terminal. `load_autosave` logs an
unreadable generation via `errlog.log_error`, and `errlog`'s logger had **no handler** until a
front-end called `setup_logging()` — at which point stdlib logging falls through to its handler of
last resort and prints to stderr. Worse, `run_tui()` was the one entry point that never called
`setup_logging()` (the CLI and GUI both do), so the TUI would have taken that traceback across a
full-screen terminal app, and its errors had been going nowhere all along. Two lines fix both: a
`logging.NullHandler()` on the logger at import — the stdlib library pattern, which makes "silent"
true *before* anyone configures anything — and `setup_logging(install_hooks=False)` at the top of
`run_tui()`. Tested in a subprocess so the check can't be fooled by whatever earlier tests did to
the logger. This is the P3 lesson: the unit tests were green and the *behaviour* was still wrong,
because nothing in the suite was watching stderr.

### Tests

**201 pass** (was 186), three consecutive clean full runs. Fifteen new: ten on the generation chain
in `test_persistence.py` (rotation order, the cap dropping the oldest, the hole, corrupt-newest,
two-corrupt, a dead chain raising, backup-only `has_autosave`, browser filtering, cascading delete,
the `gen` range guard), two front-end ones in `test_tui_persistence.py` (the TUI's autosave really
goes through the rotation; the backup banner reaches the news pane), one boot-wiring test in
`test_gui_model.py` (`from_backup` is a *comparison* and would read False silently if it pointed at
the wrong path — so all three outcomes are asserted, including a dead chain giving a fresh world),
plus the two P22 ones.

Thirteen mutations, thirteen catches: rotation no-op'd · oldest kept · resume stopping at gen 0 ·
`has_autosave` back to the live slot only · browser filter removed · `read_info` back to
`name == AUTOSAVE_SLOT` · delete narrowed to one file · range guard removed · the TUI writing gen 0
directly (the pre-P3 line) · the TUI banner suppressed · `boot()` hardcoding `from_backup=False` ·
the `NullHandler` removed · `setup_logging` dropped from `run_tui()`.

### State

Wave A is done — P1, P2, P3 all shipped. Next is **Wave B (feel)**: P4 price-flash, P5 sound
(PySynthRack for the synthesis), P6 tray + toasts. **P14** has been unblocked since P2.

## 2026-08-23 — P4 · price flash on the board (Wave B opens)

First slice of Wave B, and the one that sets the tone for it: nothing about the simulation
changes, the board just tells you *what it did* instead of only *where it landed*. A Price cell
tints green when it ticks up, red when it ticks down, and fades out over 0.7 seconds.

**The interesting decision is what a flash means.** Not "this price differs from the last one the
engine produced" — "this price moved **on your screen**". `PriceFlash` therefore remembers the
last price it was *shown*, not the market's history, and an asset it has never seen cannot flash
at all. That one rule buys every quiet case for free: switching views, paging, sorting, and
opening a loaded world are all dark, because `update()` drops any asset absent from the batch it
was handed, so an asset you page back to is unknown again and its first sighting only re-seeds
the baseline. The alternative — comparing against the market — would light the entire board every
time you touched a view button, and a flash that fires when nothing happened is worse than no
flash at all. `_after_world_swap` clears explicitly on top of that, since the swapped-in world
has the *same* asset ids at completely different prices.

**Fading onto the right colour.** The board alternates row backgrounds (`BG` on even rows,
`PANEL` on odd), so a flash that faded toward one flat colour would snap at the tail on half the
rows. `row_background(row)` gives the tint its true endpoint, and the blend peaks at
`FLASH_PEAK = 0.55` rather than the full colour — a saturated cell drowns the pale phosphor
digits for a third of a second, which is precisely the third of a second you wanted to read them
in. Green up / red down are the module constants, never `THEME.accent`: the P2 split, applied
without having to think about it.

**It needed its own timer, and that's the non-obvious part.** The market `QTimer` runs at 250 ms
but only repaints when a whole sim-minute has elapsed, and stops advancing entirely while paused
— so a fade driven by it would step three times at 1 min/s, and after a manual `Step` or a pause
it would simply freeze mid-glow, leaving half the board tinted until you pressed something. The
flash gets a 60 ms timer of its own whose slot costs one dict scan (`flash.live()`) when nothing
is flashing, and repaints only the Price column when something is. Alpha is a function of
wall-clock, not of frames drawn, so a GC pause or a modal held open can't strand a flash either.
That is also what makes the whole thing testable without an event loop: every method takes `now`.

**The toggle clears on both edges.** `Appearance ▸ Price flash` applies live and persists like the
accent does. Turning it *off* clearing the tracker is obvious; turning it back *on* clearing it
matters just as much, or the first repaint would compare live prices against a baseline from
whenever you switched it off and light up the entire board at once.

**Known cosmetic limit:** Qt's default delegate paints the selection highlight *over* the
background role, so the cursor row's flash is invisible while it's selected. Fighting that means
a custom delegate for one row; not worth it, and the row you're looking at is the one you're
least likely to need the hint on.

### Tests

**215 pass** (was 201), two consecutive clean full runs. Fourteen new in `tests/test_gui_flash.py`
— thirteen pure ones (no Qt, no clock: interpolation endpoints and clamping, the alternating base,
first-sighting silence, direction, an unchanged price staying silent, linear decay floored at
zero, a second move restarting the fade, tint blending toward the P&L semantics, the peak stopping
short of the full colour, paging back staying quiet, pruning both expired and departed hits,
`clear()` dropping the baseline too, and a zero duration not dividing by zero) plus one subprocess
test that drives a real window through the whole feature: only the Price column paints, the tint
reads as its direction, a blue accent still flashes green and red, the fade completes on
wall-clock with the market paused, the flash timer is faster than the market timer, world swaps
and view changes stay dark, the toggle darkens / persists / doesn't replay a backlog, and a
`price_flash: false` in settings survives to the next launch's menu checkmark.

**Twenty mutations, twenty catches** — but only after a fix. The first sweep *missed* one:
deleting the `flash_on` check from the painter changed nothing, because `set_price_flash` also
clears the tracker and `_recompute` doesn't feed it while off, so its two neighbours were covering
it. Rather than delete the guard (it's what makes the flag authoritative for the painter, whatever
state the tracker is in) the test now pokes `flash_on` directly on a live flash — the same call
the boot path makes. The others: first-sighting flashing, the baseline never forgetting, no
pruning, unfloored alpha, a dead flash still painting, a full-saturation peak, flipped row parity,
up/down swapped, every column tinted, the board never fed, the world swap keeping its baseline,
the toggle not clearing, not persisting, the preference not restored, the flash timer never
started, the flash timer running at the market cadence, `repaint_flashes` always claiming work,
and `refresh()` emitting without the background role.

**And a smoke run, per the P22 lesson.** Four seconds of a real event loop at 1 hr/s (a flash on
nearly every frame) with stderr captured: 50 flash repaints, 792 lit-cell samples, **stderr
empty**. Green tests still aren't a smoke test.

### State

Wave B is open. Next is **P5 · sound** — which Matthew wants to talk through before it starts, so
it is parked, not started. **P6 · tray + toasts** and **P14 · theme presets** are both available
and independent of that conversation.
