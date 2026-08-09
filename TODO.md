# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-09**, on top of commit `3a54dd3`.

---

## State right now

**Uncommitted**: P19, P18, P21 and P2 are done, tested and green in the working tree — they still
need a commit and a push. Nothing is half-finished.

* **186 tests pass** — `python -m pytest` (needs `textual<0.72`, plus `PySide6` + `pyqtgraph` for
  the Qt tests, which skip if it isn't installed). Ran three times clean after each slice.
* Shipped this session:
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

### Commit these first

```
git add -A
git commit -m "P19: ticker uses fmt.money() so sub-cent coins keep their digits" -m "The tape hardcoded :,.2f, so every penny coin read `FRG 0.00` while the board right below showed $0.0000001834. Swapped _build_ticker (tui) and ticker_text (gui/model) to money(), which keeps ~4 significant figures under a cent."
git commit -m "P18: change columns read - until the lookback is real" -m "On a young world every window clamps to tick 0, so 1D/7D/31D printed the same number - correct, but indistinguishable from a broken column. Display now goes through _chg_col/chg_col (None until _has_window/has_window) and a shared _pct_cell. Sorters still call _chgNd/chg_pct so movers and sort-by-1D% keep ranking by change-since-open; the movers header hint says 'since open' while that is what it ranks by."
git commit -m "P21: the ticker timer survives app teardown" -m "The 0.3s interval can fire once after the app is gone; #ticker no longer exists and screen_stack is back to 1, so the modal guard missed it and _tick_ticker raised NoMatches. Made the suite intermittently red. Bail out of _on_timer when not is_running."
git commit -m "P2: the accent picker applies live, no restart" -m "ACCENT/ACCENT_HI/SELECTION were module constants resolved at import and baked into stylesheet strings at widget-build time, so rebinding did nothing. They now live on a mutable THEME object read at format time; the constants are deleted and a test keeps them gone. Accent styling on long-lived widgets moved into two re-runnable passes (_apply_theme and the new _style_panels) that set_accent re-runs. GREEN/GREEN_HI/RED stay module constants - P&L semantics are not themeable."
git push
```

(One `git add -A` then four commits as written, or `git add -p` if you want them truly separate.)

---

## Next up

### 1. P3 · Autosave generations (S) — finishes Wave A

Rotate `autosave` → `.1` → `.2`; a corrupt newest falls back down the chain at resume. Lives in
`trader_pro/persistence.py` (`autosave_path`, `has_autosave`, `load_game`) with the resume paths
in `gui/model.boot()` and `tui.run_tui()`. Small and self-contained.

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
  heredoc.
