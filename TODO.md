# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-23**. Head of `origin/master`: `6a46ffe` (P22), pushed.

---

## State right now

**Wave A is complete** — P1, P2 and P3 are all shipped, committed *and* pushed. **201 tests pass**
(`QT_QPA_PLATFORM=offscreen python -m pytest`), three consecutive clean full runs. Working tree is
clean; nothing is half-finished.

The last two commits on `master`:

* **`059e56b` · P3 · Autosave generations** — every autosave rotates `autosave` → `.1` → `.2`
  (renames, not copies) before writing, and resume walks the chain newest-first until something
  loads. When it lands on a backup it says so: amber in the TUI news pane, red in the GUI log.
  `tui_p3_backup_resume.png` is the screenshot.
* **`6a46ffe` · P22 · The error log was never silent** — unplanned, and the reason to keep doing
  end-to-end smoke runs. `errlog`'s logger had no handler until `setup_logging()` ran, so stdlib
  logging fell through to its handler of last resort and printed to **stderr** — and `run_tui()`
  never called `setup_logging()` at all. Fixed with a `logging.NullHandler()` at import plus the
  missing `setup_logging` call.

### Three things worth remembering from P3

1. **Rotate before the write** — so a crash in that window leaves `.1` and *no* gen 0. That is why
   `has_autosave()` asks about the whole chain, not the live slot.
2. **Dropping the oldest explicitly is not redundant.** `os.replace` already overwrites the file
   below, but only while the chain is full; punch a hole in it and the tail never ages out.
3. **Backups are not slots.** Hidden from the `Ctrl+L` browser, and deleting the autosave takes
   all three — otherwise the slot you deleted resumes from `.1` at next launch.

---

## Next up

### 1. Wave B — feel

**P4 · Price-flash on the board** (S) — cells pulse P&L-green/red on tick moves, then fade. The
natural first one: small, visible, and it respects the accent-vs-semantics split P2 established
(flashes are P&L semantics, so `GREEN`/`RED`, not the themeable accent).

**P5 · Sound** (M) — retro chirps: fill, cancel, margin-call klaxon, black-swan stinger.
**Matthew wants PySynthRack dropped in for the synthesis.** Appearance ▸ Sound toggle persists
through P1's `get_setting`/`update_settings`.

**P6 · Tray + toasts** (M) — minimise-to-tray, Windows toasts for fills / margin calls / black
swans while hidden. The idle-friendly north star, delivered.

### 2. Or jump the queue

**P14 · Theme presets + CRT scanlines** (S/M) — unblocked since P2; presets are just named accents
passed to `TraderGUI.set_accent()`.

### Small thing noticed, not filed

The TUI news pane **clips long lines instead of wrapping** at narrow terminal widths — visible in
`tui_p3_backup_resume.png`, where the existing "Resumed your last game · …" line is cut mid-word.
Pre-existing, cosmetic, and only at ~132 columns or less. Fold it into P4 if it annoys you.

---

## Working notes (things that cost time to rediscover)

* **Running the suite from a cloud session**: the mounted-folder VM has no pytest and no network.
  Stage the repo into the cloud container, copy it out of the read-only uploads dir, then
  `pip install --break-system-packages pytest "textual<0.72" PySide6 pyqtgraph` and
  `QT_QPA_PLATFORM=offscreen python -m pytest`. ~42 s.
* **Qt tests run offscreen in subprocesses** — PySide6's shiboken import hook and Textual's lazy
  modules collide in one interpreter, so they never share a process.
* **Textual screenshots** come straight out of the pilot: `app.export_screenshot()` → SVG, then
  `cairosvg` → PNG. **GUI screenshots**: `gui.resize(...)`, `gui.show()`, `app.processEvents()`,
  `gui.grab().save(path)`.
* **Textual stays pinned `<0.72`** — 0.72.0 deadlocks the trade-dialog teardown
  (`docs/freeze-bug/README.md`).
* **An intermittent red suite is a bug report.** P21 came out of one flaky run and turned out to be
  deterministic. Re-run a failure three times against a pristine copy before shrugging it off.
* **Green tests are not a smoke test.** P22 was invisible to 201 passing tests because nothing was
  watching stderr. Run the feature end-to-end and *read the output* before calling a slice done.
* **Theming rule of thumb** (post-P2): read `THEME.accent` at *format* time, never snapshot it.
  Long-lived widgets get styled from `_style_panels()`, not inline. Modal dialogs are exempt.
* **Commits and pushes are Matthew's to run**, from PowerShell: repeated `-m` flags, never a
  heredoc, no backticks in the message. **One explicit `git add <paths>` per commit.**
