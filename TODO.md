# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-04**, at commit `c401f52` (pushed to `origin/master`).

---

## State right now

Everything is committed, pushed, and green. Working tree clean.

* **175 tests pass** — `python -m pytest` (needs `textual<0.72`, plus `PySide6` + `pyqtgraph` for
  the Qt tests, which skip if it isn't installed).
* Shipped this session: **P1** (GUI session memory), **P16** (TUI new-world dropdowns),
  **P17** (coalesced held-key stepping), and a `.gitattributes` that settled the line-ending noise.
* Nothing is half-finished. There is no work-in-progress to reconstruct.

---

## Next up

### 1. P2 · Live accent repaint (M) — the planned Wave A slice

Retire "restart to apply" from the Appearance ▸ accent-colour picker.

The blocker is structural, and it's the whole slice: `gui/model.py` binds `ACCENT` / `ACCENT_HI` /
`SELECTION` as **module-level names at import time**, and `gui/app.py` interpolates those names
into stylesheet strings when the widgets are built. Rebinding the module attribute later changes
nothing, because the values were already baked into the strings. So the work is to route the
palette through a **mutable theme object** (or a `theme()` accessor) that widgets can be asked to
re-read, then have `action_pick_accent` restyle the live widgets instead of only writing
`settings.json`.

Keep the accent-vs-P&L split intact: `GREEN`/`GREEN_HI`/`RED` are *semantics* (profit green, loss
red, always) and must not become themeable. Only chrome follows the accent. Unlocks **P14** (theme
presets + CRT scanlines).

### 2. P18 · Honest change columns (S) and P19 · Ticker precision (XS)

Both surfaced from a screenshot of a 31-minute-old world. Details, file pointers and the sorting
gotcha are in `design.md` §11. P19 is close to a one-line change — `fmt.money()` already handles
sub-cent prices and is already imported at both call sites.

---

## Working notes (things that cost time to rediscover)

* **Running the suite from a cloud session**: the mounted-folder VM has no pytest and no network.
  Stage the repo into the cloud container, `pip install pytest "textual<0.72" PySide6 pyqtgraph`,
  then `QT_QPA_PLATFORM=offscreen python -m pytest`. ~35 s.
* **Qt tests run offscreen in subprocesses** — PySide6's shiboken import hook and Textual's lazy
  modules collide in one interpreter, so they never share a process.
* **Textual screenshots** come straight out of the pilot: `app.export_screenshot()` → SVG, then
  `cairosvg` → PNG. That's how `tui_new_world*.png` were made; handy for reviewing a UI change.
* **Textual stays pinned `<0.72`** — 0.72.0 deadlocks the trade-dialog teardown
  (`docs/freeze-bug/README.md`).
* **Commits and pushes are Matthew's to run**, from PowerShell: repeated `-m` flags, never a
  heredoc.
