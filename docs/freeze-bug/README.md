# Bug: TUI freezes after the trade dialog closes

**Status:** **RESOLVED** for the supported config — (1) pinned `textual>=0.50,<0.72`, and
(2) reworked `TradeDialog` so it logs/refreshes after it pops instead of from inside itself.
**Reported:** "I buy a crypto, then after the buy screen disappears the game freezes — not even Ctrl-C stops it."
**Component:** `trader_pro/tui.py` — `TradeDialog` (the per-asset buy/sell/short/cover modal).

## TL;DR / resolution

Two separate problems were hiding behind each other in this dialog:

1. **The freeze** (Textual **>=0.72** regression) — dismissing the modal deadlocks Textual's
   screen teardown; the whole TUI locks up, Ctrl-C included. Fixed by pinning `textual<0.72`
   (0.71.0 is the last good release). Details below + the version bisect.
2. **A `NoMatches('#log')` crash on buy** (surfaced once the freeze was gone on 0.71.x) — the
   dialog called `self.app._log(...)` / `self.app._refresh()` **while the modal was still on
   top**, reaching into the *main screen's* widgets. On Textual 0.71.x `app.query_one` can't see
   the base screen from inside a modal, so it raised. Fixed by having the dialog just
   `dismiss((verb, qty, sym, result))` and letting the app log + redraw from its
   `push_screen` callback (`TraderTUI._on_trade_closed`) **after** the modal has popped.

With both in place: on 0.71.x you can open the dialog, buy/sell/short/cover or cancel, the board
updates, and the app stays responsive. On >=0.72 the dialog still freezes (the regression is
upstream), so the pin stays until that's fixed or the dialog is moved off `ModalScreen`.

---

## Symptom

Open the per-asset trade dialog (Enter on a row in the live TUI), then let it close — either
by completing a buy or by pressing **Esc** to cancel. The dialog disappears, but the whole
TUI is then frozen: no keys do anything, and **Ctrl-C does not quit**. The only way out is to
kill the terminal/process.

It is **not** crypto-specific — the user happened to buy a crypto, but the freeze happens for
any asset, and on cancel as well as on a filled order. The buy itself succeeds (cash/position
update correctly); the freeze is purely in closing the dialog.

## Root cause

Dismissing the modal triggers Textual's screen-teardown:

```
TradeDialog.dismiss()  ->  App.pop_screen()  ->  do_pop()  ->  _replace_screen()  ->  screen.remove()
```

`screen.remove()` waits for the dismissed dialog's child widgets to shut down (each widget has
its own message-pump task). In this app that wait **never completes** — `do_pop` is stuck
forever and every dialog widget is still alive. With the App's message loop parked inside that
never-finishing `do_pop`, the event loop goes idle and **stops dispatching input**.

Ctrl-C does nothing because Textual puts the terminal in raw mode: Ctrl-C arrives as an
ordinary keystroke (byte `0x03`) for the app to handle, not as a SIGINT the OS can use to kill
the process. Since input is no longer dispatched, that keystroke is simply never read.

The smoking gun is the live asyncio task dump taken at the moment of the freeze
(`asyncio-task-dump.txt`):

```
TASK: Task-285  coro= App.pop_screen.<locals>.do_pop   done= False     <-- stuck forever
       app.py 3119 do_pop
TASK: message pump TradeDialog()                       done= False     <-- never torn down
TASK: message pump Horizontal(id='trade-buttons')      done= False
TASK: message pump Button(id='buy', ...)               done= False
TASK: message pump Button(id='sell', ...)              done= False
TASK: message pump Button(id='short', ...)             done= False
TASK: message pump Button(id='cover', ...)             done= False
TASK: message pump Input(id='qty')                     done= False
TASK: message pump Static(id='trade-info')             done= False
TASK: message pump Static(id='trade-msg')              done= False
TASK: message pump Vertical(id='trade-box')            done= False
```

`thread-stacks.txt` (a faulthandler dump of all OS threads) corroborates it: the input thread
is alive and reading the tty, and the main thread is parked idle in `selectors.select` inside
the asyncio loop — i.e. not a CPU spin, a genuine wait that never ends.

## What we ruled out

The investigation tested a lot of hypotheses against the real app (driven through a pseudo-tty)
and headlessly (`run_test`). None of these were the cause, and none fixed it:

- **Not** the old `call_later` indirection (the comment in `_act`/`on_button_pressed` claims it
  fixes a "buy-then-freeze bug"; it does not).
- **Not** the order execution, the `_refresh()` after the trade, or the `_log` call.
- It **is** Textual-version-dependent: a regression introduced in **Textual 0.72.0** (see the
  bisect below). 0.71.0 and earlier are fine; 0.72.0 through the dev build all freeze.
- **Not** specific to crypto, nor to buying (cancel-with-Esc freezes too).

It is **content/layout-sensitive**: a freshly-written minimal `ModalScreen` (`Static + Input`)
tears down cleanly, while `TradeDialog` deadlocks reliably.

**The button count is NOT the cause** (tested directly — see
`tests/test_tui_dialog_button_count.py`). Rendering the dialog with **0, 1, 2, 3 or 4** Buttons
all freeze on dismiss. We also ruled out, one factor at a time, the dismiss style
(`call_later` vs direct `dismiss()`), where the info text is built (`compose` vs an `on_mount`
`.update()`), the per-action handlers (`on_input_submitted` / `_act`), and the extra Static
widgets — none of them flip it. Yet a separate, near-identical minimal modal class stays
responsive. So the trigger is a genuinely fragile race in Textual's teardown of *this* screen,
not any single ingredient — which is exactly why structural tweaks have been whack-a-mole and a
clean rebuild (or dropping the modal) is the dependable fix.

## Reproduce it

Headless / cross-platform (works on Windows, no extra deps beyond `textual`):

```
python tests/test_tui_trade_dialog_freeze.py
# -> RESULT: FROZEN (bug reproduced)
```

Or against the live terminal app on Linux/macOS/WSL (needs `pexpect`):

```
python scripts/repro_trade_dialog_freeze.py
```

Or by hand: `python play_tui.py`, press Enter on the first row, press Esc — the app is now dead
to the keyboard.

## Version regression (bisected)

The freeze is a **Textual regression first shipped in 0.72.0**. Bisected with the headless
reproduction (`scenario` in the regression test), against the unmodified original dialog:

| Textual | Result |
|--------:|:-------|
| 0.50.0  | alive  |
| 0.68.0  | alive  |
| 0.70.0  | alive  |
| 0.71.0  | **alive (last good)** |
| 0.72.0  | **FROZEN (first bad)** |
| 0.73 / 0.77 / 0.86 / 1.0.0 / 8.2.7 / dev `main` | FROZEN |

So `requirements.txt` (`textual>=0.50`) allows a broken version. Two quick fixes either work:

- **Pin Textual:** `textual>=0.50,<0.72` (or `==0.71.0`) — the dialog works as-is, no game-code
  change. Cost: you stay on a 2024-era Textual.
- **Make the game version-proof:** rebuild the dialog so it tears down cleanly on modern Textual
  (see below). This is the durable fix and lets you track current Textual.

Worth reporting upstream to Textualize with the minimal repro (`scripts/repro_trade_dialog_freeze.py`)
— it's their regression, and a fix there would let the pin be lifted.

## Fix directions (deferred — for the next session)

1. **Robust:** don't use a `ModalScreen` for trading at all. Pressing Enter on a row could
   pre-fill the existing command line (`#cmd`) with `buy <SYM> ` and focus it — the
   command-line trade path already works and never touches the modal teardown.
2. **Keep the popup:** keep `TradeDialog` a modal but shrink/guard its widget tree (drop the
   `Button`s, single focused `Input`, content that can't wrap) so teardown completes. This was
   *not* reliable in testing — small content changes flipped it between frozen and fine — so it
   needs careful, repeated verification before trusting it.

The regression test (`tests/test_tui_trade_dialog_freeze.py`) is marked **xfail** today. When
the dialog is fixed it will XPASS — at that point remove the xfail so it guards the fix.

## Environment

- Reproduced with Python 3.10, Textual 1.0.0 and 8.2.7.
- Evidence files in this folder: `asyncio-task-dump.txt`, `thread-stacks.txt`.
