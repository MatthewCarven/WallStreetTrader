# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-09-15**. This line used to name the last pushed commit, which made it stale
the moment anything else landed — twice in one session. It doesn't any more: **ask git**
(`git status`, or `git log --oneline origin/master..HEAD` for exactly what's waiting). Pushes stay
Matthew's to run.

---

## State right now

**Waves A and B complete.** **244 tests pass** (`QT_QPA_PLATFORM=offscreen python -m pytest`),
working tree clean.

* **P4 · Price flash (GUI)** — a Price cell tints green on an up-tick, red on a down-tick, fading
  over 0.7s. Quiet by design: it compares against the last price it *displayed*, so first
  sightings, view switches, paging and loaded worlds stay dark. Its own 60ms timer, an
  **Appearance ▸ Price flash** toggle persisted via P1. `gui_p4_price_flash.png`.
* **P4b · Price flash (TUI)** — the same thing in the terminal, filed and shipped the moment it
  turned out the TUI is what gets launched. The mechanism moved to `trader_pro/flash.py`
  unchanged; the terminal-specific half is reading the DataTable's real zebra colours to fade
  onto and repainting single cells with `update_cell_at`. One `price_flash` preference governs
  **both** front-ends. `tui_p4b_price_flash.svg`.
* **`start_gui.cmd`** — the GUI has a launcher now, which is why P4 was invisible in the first place.
* **P5 · Sound — COMPLETE (2026-09-11).** L1: nine WAVs rendered at -18 dBFS from
  `sounds/patches/*.json`, auditioned, mapping settled. L2: the six winners are package data in
  `trader_pro/sounds/`; `trader_pro/sound.py` owns the mapping and derives **one cue per
  advance**; `TraderApp.on_cue` is the seam every path cues through. GUI `QSoundEffect` +
  **Appearance ▸ Sound**; TUI `winsound` / bell + `m`. One `sound` preference — `settings.py`
  moved to the package root for it. The suite runs muted (`TRADER_PRO_MUTE`, conftest).
  **Sign-off is Matthew's: an hour of play with the toggle in reach.** If a cue needs changing,
  it's a line in `sound.CUES`; if one needs re-rendering, `python scripts/render_sounds.py
  sounds/patches/<name>.json --out trader_pro/sounds`.
* **P6 · Tray + toasts — COMPLETE (2026-09-15).** **Window ▸ Minimise to tray** (off by default,
  `tray` pref): minimising parks the window behind a painted `$` tray icon and the market keeps
  ticking; toasts are Qt's own `QSystemTrayIcon.showMessage`, fire only while hidden, and make
  **the sound's pick** (`model.toast_for` → `sound.advance_cue`, one per advance). A margin call
  while hidden pauses and toasts; its popup waits for the window. `Ctrl+H` hides regardless;
  close still quits; the tray menu is Show / Play-Pause / Quit. `gui_p6_tray.png`. **Matthew to
  try in anger**: turn it on, minimise, rest a stop, walk away — the toast attribution reads as
  the Python interpreter's until P15 gives the exe an identity of its own.

### Three things worth remembering from P3

1. **Rotate before the write** — so a crash in that window leaves `.1` and *no* gen 0. That is why
   `has_autosave()` asks about the whole chain, not the live slot.
2. **Dropping the oldest explicitly is not redundant.** `os.replace` already overwrites the file
   below, but only while the chain is full; punch a hole in it and the tail never ages out.
3. **Backups are not slots.** Hidden from the `Ctrl+L` browser, and deleting the autosave takes
   all three — otherwise the slot you deleted resumes from `.1` at next launch.

---

## Next up

### 1. Wave C — trader QoL

Wave B (P4, P4b, P5, P6) is done. Wave C is engine + all three front-ends, like the L slices:

**P7 · Blotter core** (M) — record every fill (manual, triggered, liquidation) on the portfolio:
tick, side, qty, price, fee, realized P&L. Serialized with saves, **back-compat** with the saves
already out there (see `test_version_guard.py` for how the format is guarded). Unblocks P8
(blotter UI) and P9 (stats + market-close recap). The seam is the same one everything else uses:
every fill already passes through `execute_order` / `process_pending` / `liquidate_for_margin`,
and `TraderApp._advance` sees all three kinds in one place.

Then **P10 · Price alerts** (S/M) — a notify-only resting kind; `is_triggered` does the hard
part, and P6's toast + P5's cue are the notification, already built.

### 2. Or jump the queue

**P14 · Theme presets + CRT scanlines** (S/M) — unblocked since P2; presets are just named accents
passed to `TraderGUI.set_accent()`. The tray icon already repaints on an accent change.

**P15 · Icon, About, exe diet** (M) — P6's `tray_icon()` is a painted `$` on the dark ground; the
candlestick icon P15 wants is the same trick with a different drawing, and it should become the
window + tray + exe icon in one go.

### Small thing noticed, not filed

The TUI news pane **clips long lines instead of wrapping** at narrow terminal widths — visible in
`tui_p3_backup_resume.png`, where the existing "Resumed your last game · …" line is cut mid-word.
Pre-existing, cosmetic, and only at ~132 columns or less. P4 turned out to be GUI-only, so this
is still homeless — fold it into the next slice that touches the TUI.

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
* **`cairosvg` is not installed locally**, so a TUI slice gets an `.svg` and no `.png`. The
  export itself is unchanged: `app.export_screenshot()` inside `run_test`.
* **Don't measure a 0.7s effect with `pilot.press()`.** It can take most of a second to return
  (P17's key coalescing, plus the pilot waiting for the app to settle) — longer than the thing
  you're trying to observe. A screenshot taken that way came back empty and looked like a broken
  feature; it was a broken measurement. Drive `_advance` + `_refresh` directly and hand the
  painter an explicit `now`.
* **Screenshots of the GUI need a real Qt platform.** `QT_QPA_PLATFORM=offscreen` has no fonts
  in this environment and grabs a window full of tofu boxes. Drop the env var (plain
  `python`), `gui.show()`, `app.processEvents()`, then `gui.grab().save(...)` — and clear the
  board selection first, or the selection highlight hides the cell you're trying to show.
* **A flash the selected row can't show.** Qt's default delegate paints the selection highlight
  over `Qt.BackgroundRole`, so the cursor row never shows its price flash. Would need a custom
  delegate; judged not worth it (P4).
* **The suite is muted.** `conftest.py` sets `TRADER_PRO_MUTE`, so real players are never built
  under pytest and a green run is a silent one. To see cues in a test, install a recorder on
  `gui._player` / `app._player`. A smoke run that should actually *sound* clears the var in its
  own process — and points `TRADER_PRO_SETTINGS_DIR` at the scratchpad first.
* **Theming rule of thumb** (post-P2): read `THEME.accent` at *format* time, never snapshot it.
  Long-lived widgets get styled from `_style_panels()`, not inline. Modal dialogs are exempt.
* **Pushes are Matthew's to run.** Commits from the session are fine (the top-level
  `CLAUDE.md` says so) — this note used to say both, from the cloud sessions where git wasn't
  usable at all. When a command *is* handed over, it's PowerShell: repeated `-m` flags, never a
  heredoc, no backticks in the message, **one explicit `git add <paths>` per commit**.
