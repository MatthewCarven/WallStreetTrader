# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-09**, at commit `b102a41` (pushed to `origin/master`).

---

## State right now

Everything is committed, pushed, and green. Working tree clean.

* **186 tests pass** — `python -m pytest` (needs `textual<0.72`, plus `PySide6` + `pyqtgraph` for
  the Qt tests, which skip if it isn't installed). Ran three times clean after each slice.
* Shipped this session — **all four landed in the single commit `b102a41`** (see the note below):
  * **P19 · Ticker precision** — the tape uses `fmt.money()`, so `PEPE2 $0.00000007272` instead
    of `PEPE2 0.00`. Both front-ends.
  * **P18 · Honest change columns** — 1D / 7D / 31D show a dim `—` until the world is actually
    old enough for that lookback, then light up one by one. Sorters untouched: they still rank
    by `_chgNd` / `chg_pct` (change-since-open on day zero), and the movers header hint says
    `since open` while that's what it's ranking by.
  * **P21 · Ticker timer survives teardown** — unplanned. The 0.3 s interval could fire after
    the app was gone and raise `NoMatches` on `#ticker`; that's what made the suite go red one
    run in ~four. One-line `is_running` guard in `_on_timer`.
  * **P2 · Live accent repaint** — the Wave A slice. The palette moved onto a mutable `THEME`
    object read at format time; `_apply_theme()` + the new `_style_panels()` are idempotent and
    re-run on `set_accent()`. "Restart to apply" is gone.
* Every new test was mutation-checked: revert the fix, watch the test fail, restore. Six
  mutations across the four slices, six catches.
* Nothing is half-finished. There is no work-in-progress to reconstruct.

> **Why one commit for four slices.** The handover block in this file said `git add -A` and *then*
> four `git commit` lines — `-A` stages the whole tree, so the first commit took everything and the
> other three reported "nothing to commit". `b102a41` is complete and correct; only its message is
> narrow. An empty annotation commit records that. **Next time: one explicit `git add <paths>` per
> commit, never a single `git add -A` up front.**

---

## Next up

### 1. P3 · Autosave generations (S) — finishes Wave A

Rotate `autosave` → `.1` → `.2`; a corrupt newest falls back down the chain at resume. Lives in
`trader_pro/persistence.py` (`autosave_path`, `has_autosave`, `load_game`) with the resume paths
in `gui/model.boot()` and `tui.run_tui()`. Small and self-contained — the interesting part is the
fallback test: write a deliberately corrupt newest generation and assert resume lands on `.1`
with the world intact.

### 2. Then Wave B — feel

**P4** price-flash on the board (S), **P5** sound (M — Matthew wants PySynthRack dropped in for
the synthesis), **P6** tray + toasts (M). P5 and P6 both want a settings key, which P1 already
provides.

**P14** (theme presets + CRT scanlines) is unblocked now that P2 has landed — presets are just
named accents passed to `TraderGUI.set_accent()`.

---

## Working notes (things that cost time to rediscover)

* **Running the suite from a cloud session**: the mounted-folder VM has no pytest and no network.
  Stage the repo into the cloud container, copy it out of the read-only uploads dir, then
  `pip install --break-system-packages pytest "textual<0.72" PySide6 pyqtgraph` and
  `QT_QPA_PLATFORM=offscreen python -m pytest`. ~35 s.
* **Qt tests run offscreen in subprocesses** — PySide6's shiboken import hook and Textual's lazy
  modules collide in one interpreter, so they never share a process.
* **Textual screenshots** come straight out of the pilot: `app.export_screenshot()` → SVG, then
  `cairosvg` → PNG. **GUI screenshots** are simpler: `gui.resize(...)`, `gui.show()`,
  `app.processEvents()`, `gui.grab().save(path)` — that's how `gui_p2_*.png` were made, and it's
  the fastest way to eyeball a theming change.
* **Textual stays pinned `<0.72`** — 0.72.0 deadlocks the trade-dialog teardown
  (`docs/freeze-bug/README.md`).
* **An intermittent red suite is a bug report.** P21 came out of one flaky run; the repro turned
  out to be deterministic (exit the pilot, call the timer callback by hand). Re-run a failure
  three times against a pristine copy before shrugging it off as noise.
* **Theming rule of thumb** (post-P2): read `THEME.accent` at *format* time, never snapshot it.
  If you add a long-lived widget with an accent in its stylesheet, style it from
  `_style_panels()` rather than inline — otherwise it silently stops following the picker.
  Modal dialogs are exempt: they're rebuilt on every open.
* **Commits and pushes are Matthew's to run**, from PowerShell: repeated `-m` flags, never a
  heredoc, no backticks inside the message (PowerShell's escape character). **One explicit
  `git add <paths>` per commit** — see the note above.
