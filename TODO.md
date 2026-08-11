# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-10**. Previous commit on `origin/master`: `6cd79ac`.

---

## State right now

**Wave A is complete** — P1, P2 and P3 are all shipped. **201 tests pass**
(`QT_QPA_PLATFORM=offscreen python -m pytest`), three consecutive clean full runs.

Shipped this session, **uncommitted on disk** — the commit block is at the bottom of this file:

* **P3 · Autosave generations** — every autosave rotates `autosave` → `.1` → `.2` (renames, not
  copies) before writing, and resume walks the chain newest-first until something loads. When it
  lands on a backup it says so: amber in the TUI news pane, red in the GUI log.
  `tui_p3_backup_resume.png` is the screenshot.
* **P22 · The error log was never silent** — unplanned, and the reason to keep doing end-to-end
  smoke runs. `errlog`'s logger had no handler until `setup_logging()` ran, so stdlib logging fell
  through to its handler of last resort and printed to **stderr** — and `run_tui()` never called
  `setup_logging()` at all. P3's resume path is the first thing the TUI logs, so a torn autosave
  would have dumped a 60-line traceback over a full-screen terminal app. Fixed with a
  `logging.NullHandler()` at import plus the missing `setup_logging` call.

Thirteen mutations, thirteen catches. Nothing is half-finished.

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

---

## Commit block — paste as-is

Two commits. P3 first (it carries the one-line `setup_logging` call in `tui.py`, since that file
is in both), then the P22 half that stands alone. Each is green on its own.

```powershell
git add trader_pro/persistence.py trader_pro/cli.py trader_pro/tui.py trader_pro/gui/app.py trader_pro/gui/model.py tests/test_persistence.py tests/test_tui_persistence.py tests/test_gui_model.py tui_p3_backup_resume.png design.md README.md WORKLOG.md TODO.md

git commit -m "P3: autosave generations - rotate autosave to .1 and .2, resume falls back" -m "Every autosave now rotates before it writes (oldest dropped, each generation renamed back one step), and resume walks the chain newest-first until a file actually loads. Renames not copies, so rotating costs the same whatever the save weighs - which is what makes it affordable on the 30-second timer." -m "Rotating BEFORE the write leaves one observable window: a crash in it leaves .1 populated and no gen 0. So has_autosave() now asks about the whole chain rather than the live slot, or the very crash generations exist to survive would present as no-save-here-is-a-fresh-world. Dropping the oldest explicitly is likewise not redundant: os.replace already overwrites the file below, but only while the chain is full - punch a hole in it and the tail never ages out." -m "Backups are recovery files, not slots. They are hidden from the Ctrl+L browser (three near-identical rows 30 seconds apart would bury the saves you named), and deleting the autosave now takes all three, or the slot you just deleted resumes from .1 at next launch." -m "load_autosave returns (world, path) so both resume paths can compare against gen 0 and tell the player when they landed on a backup - amber in the TUI news pane, red in the GUI log. gui.model.boot() grew a third return value for it. Wave A complete." -m "Fifteen new tests, 201 pass. Thirteen mutations, thirteen catches."

git add trader_pro/errlog.py tests/test_errlog.py tests/test_version_guard.py

git commit -m "P22: the error log was never actually silent" -m "errlog's logger had no handler until a front-end called setup_logging(), so stdlib logging fell through to its handler of last resort and printed the whole report to stderr. run_tui() was also the one entry point that never called setup_logging() at all - its errors had been going nowhere all along." -m "P3's resume path is the first thing the TUI logs, so a torn autosave would have dumped a 60-line traceback across a full-screen terminal app. Found by running the feature end-to-end; 201 passing tests never saw it, because nothing in the suite was watching stderr." -m "Fix is two lines: a logging.NullHandler() on the logger at import (the stdlib library pattern - it makes silent true before anyone configures anything), and setup_logging(install_hooks=False) at the top of run_tui(), matching the CLI. The run_tui half rode in with the P3 commit because it lives in tui.py. Tested in a subprocess so the check cannot be fooled by whatever earlier tests did to the logger."

git push
```

### Housekeeping

There is a **`.git/index.lock.stale`** file in the repo — a 0-byte leftover. A `git status` run
from the cloud session's mounted-folder VM created `.git/index.lock` and couldn't unlink it
(that VM can rename but not delete), which would have blocked your next `git add`, so it was
renamed aside. Git ignores it and it never shows in `git status`. **Delete it whenever** —
`del .git\index.lock.stale` — it is not needed for anything.
