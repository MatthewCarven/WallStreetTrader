# TODO — pick up here

Short, current, and disposable. The **full backlog lives in [`design.md` §11](design.md)**; this
file is just "where we stopped and what to do next", so the two never drift apart.

Last touched: **2026-08-23**. This line used to name the last pushed commit, which made it stale
the moment anything else landed — twice in one session. It doesn't any more: **ask git**
(`git status`, or `git log --oneline origin/master..HEAD` for exactly what's waiting). Pushes stay
Matthew's to run.

---

## State right now

**Wave A complete; Wave B open and now landing in both front-ends.** **219 tests pass**
(`QT_QPA_PLATFORM=offscreen python -m pytest`), working tree clean.

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

### Three things worth remembering from P3

1. **Rotate before the write** — so a crash in that window leaves `.1` and *no* gen 0. That is why
   `has_autosave()` asks about the whole chain, not the live slot.
2. **Dropping the oldest explicitly is not redundant.** `os.replace` already overwrites the file
   below, but only while the chain is full; punch a hole in it and the tail never ages out.
3. **Backups are not slots.** Hidden from the `Ctrl+L` browser, and deleting the autosave takes
   all three — otherwise the slot you deleted resumes from `.1` at next launch.

---

## Next up

### 1. Wave B — feel (continued)

**P5 · Sound** (M) — retro chirps: fill, cancel, margin-call klaxon, black-swan stinger.
**Talked through 2026-08-23; settled:**

* **PySynthRack is a build-time tool, not a dependency.** Author patches, render them to WAVs from
  the command line, commit *both* (a chirp stays re-renderable, not a mystery binary). Trader Pro
  gains no runtime dep: PySide6 6.11.1 already ships QtMultimedia, so `QSoundEffect` plays them.
  This is what keeps P15's exe diet alive — a runtime PySynthRack would drag in numpy + scipy +
  a PortAudio binary.
* **The rendering recipe.** `modules/diskwriter.py` is a sink: audio in, 16-bit mono WAV out at the
  backend's sample rate, path as a parameter. Drive it headless with
  `python -m pysynthrack --cli --patch p.json --seconds N`, from PySynthRack's own `.venv`
  (`-=Programming=-/Python Synthesiser 2/Python Synthesizer/.venv`) — numpy/scipy/sounddevice are
  already there. **Unverified:** whether the CLI transport needs a real output device, or whether
  a dummy/offline backend is required on a machine with none.
* **All four events make a sound**: your own fills, resting orders (fired + cancelled), the
  margin call, the black swan.
* **And all of them are quiet.** Matthew's steer, and it overrides the backlog's "klaxon" and
  "stinger" wording: the events differ in *character*, not in volume. Short, soft, low-headroom —
  something you can leave on for an hour without reaching for the toggle. If one needs more
  presence it earns it at the audition, not by default.
* **Two slices.** *L1 sound design* — patches + WAVs, rendered and auditioned, nothing wired, so a
  sound you dislike costs nothing to throw away. *L2 wiring* — playback, the Appearance ▸ Sound
  toggle persisted via P1 exactly as P4's flash toggle is, and the TUI's terminal bell where it's
  a one-liner.
* **The catch to plan around:** the session doing the work can't *hear* the output. Matthew is the
  ears; expect a render → audition → adjust loop, and prove that loop on one sound before
  authoring all four.

**P6 · Tray + toasts** (M) — minimise-to-tray, Windows toasts for fills / margin calls / black
swans while hidden. The idle-friendly north star, delivered. **Independent of the sound
conversation** — this is the one to pick up if P5 stays parked.

### 2. Or jump the queue

**P14 · Theme presets + CRT scanlines** (S/M) — unblocked since P2; presets are just named accents
passed to `TraderGUI.set_accent()`.

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
* **Theming rule of thumb** (post-P2): read `THEME.accent` at *format* time, never snapshot it.
  Long-lived widgets get styled from `_style_panels()`, not inline. Modal dialogs are exempt.
* **Pushes are Matthew's to run.** Commits from the session are fine (the top-level
  `CLAUDE.md` says so) — this note used to say both, from the cloud sessions where git wasn't
  usable at all. When a command *is* handed over, it's PowerShell: repeated `-m` flags, never a
  heredoc, no backticks in the message, **one explicit `git add <paths>` per commit**.
