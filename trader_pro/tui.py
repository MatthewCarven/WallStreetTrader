"""Textual TUI front-end for Trader PRO — the retro live-market client.

    python play_tui.py        # or:  python -m trader_pro.tui

Wraps the same `TraderApp` logic the CLI uses, but the market *ticks live*. Browse commands
(stocks/crypto/bonds/find) repopulate the main board; trades/loans/predictions print a short
line to the news log; `help` and `look` open a panel. Requires `textual`.

Retro layer (V1.6): an amber scrolling ticker tape under the header, a per-asset price-chart
pane, a top-movers view + a sort-by-%-change toggle, and a green-phosphor colour scheme.
"""

from __future__ import annotations

import re
import time
from collections import namedtuple

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static
from rich.text import Text

from .cli import TraderApp
from .core import AssetKind, Order, OrderSide, World, execute_order, load_seed_universe
from .core.engine import DAY, HOUR, WEEK
from .persistence import (
    SAVES_DIR, save_game, load_game, list_saves, delete_save, slot_path,
    autosave_path, has_autosave, AUTOSAVE_SLOT,
)

# Live-play speeds as ticks (sim-minutes) advanced per REAL second. `_on_timer` accumulates
# wall-clock time and steps the market by the elapsed amount, so pacing is frame-rate independent.
# Default (index 0) is a calm 1 sim-minute per real second — "a second at a time".
SPEEDS = [("1 min/s", 1), ("10 min/s", 10), ("1 hr/s", 60), ("10 hr/s", 600)]
SPARK = "▁▂▃▄▅▆▇█"
BLOCKS8 = " ▁▂▃▄▅▆▇"          # 0..7 sub-cell fill for the area chart's top row
FULL = "█"
CHART_RANGES = [("1H", HOUR), ("1D", DAY), ("3D", 3 * DAY), ("1W", WEEK)]
TICKER_COLOR = "#ffb000"       # amber phosphor
AUTOSAVE_SECS = 30             # wall-clock throttle for periodic autosave while playing

# retro green-phosphor palette
GREEN = "#2fae4e"
GREEN_HI = "#38c172"
AMBER = "#ffb000"


def money(x: float) -> str:
    return f"${x:,.2f}"


def fmt_clock(t: int) -> str:
    return f"D{t // DAY} {(t % DAY) // HOUR:02d}:{t % HOUR:02d}"


def sparkline(vals: list[float]) -> str:
    vals = [v for v in vals if v == v]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return SPARK[0] * len(vals)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


def _age(epoch: float) -> str:
    """A short human "x ago" for a save timestamp (epoch seconds)."""
    if not epoch:
        return "—"
    s = max(0.0, time.time() - epoch)
    if s < 90:
        return f"{int(s)}s ago"
    if s < 5400:
        return f"{int(s / 60)}m ago"
    if s < 129600:
        return f"{int(s / 3600)}h ago"
    return f"{int(s / 86400)}d ago"


def area_chart(vals: list[float], width: int, height: int, color: str) -> Text:
    """A filled multi-row area chart of `vals`, resampled to `width` columns and `height` rows.
    Uses full blocks plus an 8-level fractional top cell, so a 7-row panel gives ~56 levels of
    vertical resolution. Returns a coloured Rich Text (rows joined by newlines)."""
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        return Text("(not enough data yet)", style="dim")
    n = len(vals)
    if n > width:
        step = n / width
        sample = [vals[min(n - 1, int(i * step))] for i in range(width)]
        sample[-1] = vals[-1]
    else:
        sample = vals
    lo, hi = min(sample), max(sample)
    span = hi - lo
    if span < 1e-12:                       # flat line — draw a baseline mid-panel
        mid = height // 2
        rows = [(FULL * len(sample)) if r == mid else (" " * len(sample)) for r in range(height)]
        out = Text()
        for i, line in enumerate(reversed(rows)):
            out.append(line, style=color)
            if i != height - 1:
                out.append("\n")
        return out
    grid: list[str] = []
    for r in range(height):                # r = 0 is the bottom row
        chars = []
        for v in sample:
            eighths = (v - lo) / span * (height * 8)
            full = int(eighths // 8)
            rem = int(eighths % 8)
            if r < full:
                chars.append(FULL)
            elif r == full:
                chars.append(BLOCKS8[rem])
            else:
                chars.append(" ")
        grid.append("".join(chars))
    grid.reverse()                         # render top row first
    out = Text()
    for i, line in enumerate(grid):
        out.append(line, style=color)
        if i != len(grid) - 1:
            out.append("\n")
    return out


HELP_TEXT = """[b cyan]Trader PRO — TUI help[/]

[b]Keys[/]
  Space   play / pause the live clock
  0 1 2 3 4 view owned / crypto / stocks / bonds / watchlist
  5        top movers (biggest gainers & losers, whole market)
  o        sort the board by 1D %  (toggle)
  c        cycle the chart range   (1H → 1D → 3D → 1W)
  Ctrl+1…7 show / hide a board column  (toggle)
           [dim]1 Symbol · 2 Price · 3 1D% · 4 Pos · 5 Value · 6 Cost · 7 P&L[/]
  Enter   open a buy/sell dialog for the highlighted row
  [  ]     slower / faster   (1 min/s → 10 hr/s of sim-time per real second)
  s        step one minute      h  +1 hour      d  +1 day
  :        open the command line
  Ctrl+N   start a new world (profile/seed/cash/fees)
  Ctrl+S   save · Ctrl+L load (browse slots: net worth, return, age)
  q        quit  (autosaves first)

[b]Command line[/]  (press : first)
  [b]Browse[/] (fills the board):
    market            your holdings + watchlist
    stocks [n]        first n stocks (default 25)
    crypto / bonds    list a class
    movers            top gainers & losers      sort   toggle %-sort
    find <text>       search by name or symbol
    watch <SYM>       add a symbol to the watchlist
  [b]Info[/]:
    look <SYM>        price, change, recent path
    news              recent headlines     port   portfolio detail
  [b]Trade[/]:
    buy <SYM> <qty|$amt>      sell <SYM> <qty|all>
    short <SYM> <qty|$amt>    cover <SYM> [qty|all]
    predict <SYM> [1d|6h]     buy a forecast
    loan <amount>             repay [amount|all]
  [b]World[/]:
    save [name]       load [name|—]     saves   browse / load / delete slots
    clear   (clear the log)
    fees [off…diabolic]   brokerage difficulty — taxes every trade
    [dim]autosaves while you play and on quit; launch resumes your last game[/]

[dim]press Esc or q to close[/]"""


class HelpScreen(ModalScreen):
    CSS = """
    HelpScreen { align: center middle; }
    #help-box { width: 78; height: 90%; border: round $primary; background: $panel; padding: 1 2; }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close"),
                Binding("ctrl+c", "app.force_quit", "Quit", priority=True)]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(HELP_TEXT)

    def action_close(self) -> None:
        self.dismiss()


class TradeDialog(ModalScreen):
    """A buy / sell / short / cover dialog for a single asset (opened with Enter)."""

    CSS = """
    TradeDialog { align: center middle; }
    #trade-box { width: 62; height: auto; border: round $primary; background: $panel; padding: 1 2; }
    #trade-buttons { height: auto; align: center middle; margin-top: 1; }
    #trade-buttons Button { margin: 0 1; min-width: 10; }
    #qty { margin: 1 0; }
    #trade-msg { height: auto; }
    """
    BINDINGS = [("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "app.force_quit", "Quit", priority=True)]

    def __init__(self, asset_id: str):
        super().__init__()
        self.aid = asset_id
        self._closing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="trade-box"):
            yield Static(id="trade-info")
            yield Input(placeholder="quantity:  10   ·   $500   ·   all", id="qty")
            with Horizontal(id="trade-buttons"):
                yield Button("Buy", variant="success", id="buy")
                yield Button("Sell", variant="error", id="sell")
                yield Button("Short", variant="warning", id="short")
                yield Button("Cover", variant="primary", id="cover")
            yield Static(id="trade-msg")

    def on_mount(self) -> None:
        w = self.app.trader.world
        pos = w.portfolio.positions.get(self.aid)
        held = pos.quantity if pos else 0.0
        info = Text()
        info.append(f"{self.aid.split(':',1)[1]}  {w.name_of(self.aid)}\n", style="bold")
        info.append(f"price {money(w.price(self.aid))}\n")
        info.append(f"you hold {held:g}    cash {money(w.portfolio.cash)}\n", style="dim")
        info.append(f"buying power {money(w.portfolio.buying_power(w.price_of))}", style="dim")
        self.query_one("#trade-info", Static).update(info)
        self.query_one("#qty", Input).focus()

    def _amount(self, token: str):
        token = token.strip().lower().replace(",", "")
        price = self.app.trader.world.price(self.aid)
        try:
            return float(token[1:]) / price if token.startswith("$") else float(token)
        except ValueError:
            return None

    def _act(self, verb: str) -> None:
        if self._closing:                 # ignore queued repeats after we've acted
            return
        w = self.app.trader.world
        pos = w.portfolio.positions.get(self.aid)
        price = w.price(self.aid)
        token = self.query_one("#qty", Input).value.strip()
        if not token:  # Empty quantity: default to max buy/sell
            if verb in ("buy", "short"):
                qty = w.portfolio.buying_power(w.price_of) / price
            elif verb == "sell":
                qty = pos.quantity if pos and pos.quantity > 0 else 0.0
            elif verb == "cover":
                qty = -pos.quantity if pos and pos.quantity < 0 else 0.0
            else:
                qty = 0.0
        else:
            if verb == "sell" and token.lower() == "all":
                qty = pos.quantity if pos and pos.quantity > 0 else 0.0
            elif verb == "cover" and token.lower() == "all":
                qty = -pos.quantity if pos and pos.quantity < 0 else 0.0
            else:
                qty = self._amount(token)
        if not qty or qty <= 0:
            self._msg("enter a valid quantity", "yellow"); return
        side = OrderSide.BUY if verb in ("buy", "cover") else OrderSide.SELL
        res = execute_order(w, Order(self.aid, side, qty))
        if not res.filled:                 # rejected: keep the dialog open, show why
            self._msg(res.message, "red")
            return
        # Success: hand the fill back and close. The app logs + redraws the board from its
        # push_screen callback (TraderTUI._on_trade_closed) AFTER we have popped -- so the modal
        # never reaches into the main screen's widgets (#log/#board/...) while it is still open.
        # Doing that from here throws NoMatches on Textual 0.71.x and is fragile on newer Textual.
        self._closing = True
        self.dismiss((verb, qty, self.aid.split(":", 1)[1], res))

    def _msg(self, text: str, style: str) -> None:
        self.query_one("#trade-msg", Static).update(Text(text, style=style))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._act(event.button.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._act("buy")

    def action_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.dismiss(None)


class NewWorldScreen(ModalScreen):
    """Ctrl+N — start a fresh world. Fields are pre-filled (seed re-rolled; profile/cash/fees
    default to the current game). Enter starts, Esc cancels. Keyboard-driven, no Buttons."""

    CSS = """
    NewWorldScreen { align: center middle; }
    #nw-box { width: 64; height: auto; border: round $primary; background: $panel; padding: 1 2; }
    #nw-box Input { margin: 0 0 1 0; }
    .nw-lbl { color: $text-muted; }
    """
    BINDINGS = [("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "app.force_quit", "Quit", priority=True)]

    def __init__(self):
        super().__init__()
        self._closing = False

    def compose(self) -> ComposeResult:
        import random
        cfg = self.app.trader.world.config
        with Vertical(id="nw-box"):
            yield Static("[b cyan]New world[/]   [dim](unsaved progress is lost — save first to keep it)[/]")
            yield Static("profile", classes="nw-lbl")
            yield Input(value=cfg.profile, id="nw-profile")
            yield Static("world seed", classes="nw-lbl")
            yield Input(value=str(random.randint(1, 99_999_999)), id="nw-seed")
            yield Static("starting cash", classes="nw-lbl")
            yield Input(value=f"{cfg.starting_cash:g}", id="nw-cash")
            yield Static("fees  (off / low / medium / high / greedy / diabolic)", classes="nw-lbl")
            yield Input(value=cfg.fee_level, id="nw-fees")
            yield Static("[b]Enter[/] start   ·   [b]Tab[/] next field   ·   [b]Esc[/] cancel", classes="nw-lbl")

    def on_mount(self) -> None:
        self.query_one("#nw-profile", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._start()

    def _start(self) -> None:
        if self._closing:
            return
        from .core import get_profile, PROFILE_NAMES
        from .core.orders import FEE_LEVELS
        cfg = self.app.trader.world.config
        raw = self.query_one("#nw-profile", Input).value.strip()
        try:
            get_profile(raw); profile = raw
        except Exception:
            profile = next((n for n in PROFILE_NAMES if n.lower() == raw.lower()), cfg.profile)
        try:
            seed = int(self.query_one("#nw-seed", Input).value.strip())
        except ValueError:
            seed = cfg.world_seed
        try:
            cash = max(1.0, float(self.query_one("#nw-cash", Input).value.strip().lstrip("$").replace(",", "")))
        except ValueError:
            cash = cfg.starting_cash
        fee_raw = self.query_one("#nw-fees", Input).value.strip().lower()
        fee_level = fee_raw if fee_raw in FEE_LEVELS else cfg.fee_level
        self._closing = True
        self.dismiss((profile, seed, cash, fee_level))

    def action_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.dismiss(None)


class SaveScreen(ModalScreen):
    """Ctrl+S — name a slot and save. Keyboard-driven (no Buttons)."""

    CSS = """
    SaveScreen { align: center middle; }
    #save-box { width: 60; height: auto; border: round $primary; background: $panel; padding: 1 2; }
    #save-box Input { margin: 1 0; }
    .sv-lbl { color: $text-muted; }
    """
    BINDINGS = [("escape", "cancel", "Cancel"),
                Binding("ctrl+c", "app.force_quit", "Quit", priority=True)]

    def __init__(self, default: str):
        super().__init__()
        self.default = default or "save"
        self._closing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="save-box"):
            yield Static("[b cyan]Save game[/]")
            yield Static("slot name  (letters / digits / - _)", classes="sv-lbl")
            yield Input(value=self.default, id="save-name")
            yield Static("[b]Enter[/] save   ·   [b]Esc[/] cancel", classes="sv-lbl")

    def on_mount(self) -> None:
        self.query_one("#save-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._closing:
            return
        raw = self.query_one("#save-name", Input).value
        name = re.sub(r"[^A-Za-z0-9_-]", "", raw).strip("-_") or self.default
        self._closing = True
        self.dismiss(name)

    def action_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.dismiss(None)


class LoadScreen(ModalScreen):
    """Ctrl+L — a slot browser: net worth, return, clock, profile, age. Enter loads the
    highlighted slot; `x` deletes it (press twice to confirm); Esc cancels."""

    CSS = """
    LoadScreen { align: center middle; }
    #load-box { width: 94; height: auto; max-height: 90%; border: round $primary; background: $panel; padding: 1 2; }
    #saves-tbl { height: auto; max-height: 20; }
    #load-msg { height: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel"),
                ("x", "delete", "Delete"),
                Binding("ctrl+c", "app.force_quit", "Quit", priority=True)]

    def __init__(self, infos, saves_dir):
        super().__init__()
        self.infos = list(infos)
        self.saves_dir = saves_dir
        self._closing = False
        self._cur = None
        self._pending_delete = None

    def compose(self) -> ComposeResult:
        with Vertical(id="load-box"):
            yield Static("[b cyan]Load game[/]   [dim]↑↓ choose · Enter load · x delete · Esc cancel[/]")
            yield DataTable(id="saves-tbl", cursor_type="row", zebra_stripes=True)
            yield Static(id="load-msg")

    def on_mount(self) -> None:
        t = self.query_one("#saves-tbl", DataTable)
        t.add_columns("Slot", "Net worth", "Return", "Clock", "Profile", "Saved")
        self._fill()
        t.focus()

    def _fill(self) -> None:
        t = self.query_one("#saves-tbl", DataTable)
        t.clear()
        if not self.infos:
            t.add_row(Text("(no saves yet)", style="dim"), "", "", "", "", "", key="__none__")
            return
        for i in self.infos:
            nm = i.name + ("  (auto)" if i.is_autosave else "")
            if i.corrupt:
                t.add_row(Text(nm, style="red"), Text("corrupt", style="red"),
                          "", "", "", _age(i.saved_epoch), key=i.name)
                continue
            nw = money(i.net_worth) if i.net_worth is not None else "—"
            ret = f"{i.return_pct:+.1f}%" if i.return_pct is not None else "—"
            tone = "green" if (i.return_pct or 0) >= 0 else "red"
            t.add_row(Text(nm, style="bold"),
                      Text(nw, justify="right"),
                      Text(ret, style=tone, justify="right"),
                      fmt_clock(i.tick),
                      i.profile,
                      _age(i.saved_epoch),
                      key=i.name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self._cur = getattr(event.row_key, "value", None)
        if self._pending_delete and self._pending_delete != self._cur:
            self._pending_delete = None
            self.query_one("#load-msg", Static).update("")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        name = getattr(event.row_key, "value", None)
        if self._closing or not name or name == "__none__":
            return
        self._closing = True
        self.dismiss(name)

    def action_delete(self) -> None:
        name = self._cur
        if not name or name == "__none__":
            return
        if self._pending_delete == name:
            delete_save(name, self.saves_dir)
            self.infos = [i for i in self.infos if i.name != name]
            self._pending_delete = None
            self._fill()
            self.query_one("#load-msg", Static).update(Text(f"deleted '{name}'", style="dim"))
        else:
            self._pending_delete = name
            self.query_one("#load-msg", Static).update(
                Text(f"press x again to delete '{name}'   (Esc cancels)", style="yellow"))

    def action_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.dismiss(None)


# ---- market board columns ---- #
# The board is built from this spec so columns can be shown/hidden at runtime. Ctrl+1..Ctrl+7
# map to the seven ids below, in this order. Each entry is (id, header, render), where `render`
# turns a per-row context (`_RowCtx`) into that column's cell. Keep the list, the Ctrl+N
# bindings, and the Ctrl+N help line in sync if you add or reorder columns.
_RowCtx = namedtuple("_RowCtx", "sym price chg qty value cost pnl")

BOARD_COLUMNS = [
    ("symbol", "Symbol",
        lambda c: Text(c.sym, style="bold")),
    ("price", "Price",
        lambda c: Text(money(c.price), justify="right")),
    ("chg", "1D %",
        lambda c: Text(f"{c.chg:+.2f}%", style="green" if c.chg >= 0 else "red", justify="right")),
    ("pos", "Pos",
        lambda c: Text(f"{c.qty:g}" if c.qty else "·", justify="right",
                       style="yellow" if c.qty < 0 else ("white" if c.qty else "dim"))),
    ("value", "Value",
        lambda c: Text(money(c.value) if c.value else "·", justify="right",
                       style="green" if c.value > 0 else ("red" if c.value < 0 else "dim"))),
    ("cost", "Cost / Share",
        lambda c: Text(money(c.cost) if c.cost else "·", justify="right", style="dim")),
    ("pnl", "P&L %",
        lambda c: Text(f"{c.pnl:+.2f}%" if c.qty and c.cost else "·", justify="right",
                       style="green" if c.pnl > 0 else ("red" if c.pnl < 0 else "dim"))),
]


class TraderTUI(App):
    CSS = f"""
    Screen {{ layout: vertical; background: #07120b; }}
    #ticker {{ height: 1; background: #000000; color: {AMBER}; padding: 0 1; }}
    #status {{ height: 4; padding: 0 1; background: #0d1f14; color: #b8f0c0; }}
    #body {{ height: 1fr; }}
    #board {{ width: 2fr; border: round {GREEN}; }}
    #side {{ width: 1fr; }}
    #equity {{ height: 6; border: round {AMBER}; padding: 0 1; }}
    #chart {{ height: 10; border: round {GREEN_HI}; padding: 0 1; }}
    #port {{ height: 1fr; padding: 0 1; background: #0d1f14; }}
    #log {{ height: 1fr; border: round {GREEN}; overflow-x: hidden; }}
    #cmd {{ dock: bottom; }}
    DataTable {{ height: 1fr; }}
    """

    BINDINGS = [
        ("space", "toggle_play", "Play/Pause"),
        ("right_square_bracket", "faster", "Faster"),
        ("left_square_bracket", "slower", "Slower"),
        ("s", "step", "Step 1m"),
        ("h", "hour", "+1h"),
        ("d", "day", "+1d"),
        ("colon", "command", "Command"),
        ("1", "view_crypto", "Crypto"),
        ("2", "view_stocks", "Stocks"),
        ("3", "view_bonds", "Bonds"),
        ("4", "view_watch", "Watch"),
        ("0", "view_owned", "Owned"),
        ("5", "view_movers", "Movers"),
        ("o", "toggle_sort", "Sort %"),
        ("c", "chart_range", "Chart range"),
        # Ctrl+1..Ctrl+7 show/hide the seven board columns (kept off the footer to avoid clutter;
        # documented in the help panel). Ids/order must match BOARD_COLUMNS.
        Binding("ctrl+1", "toggle_column('symbol')", "Col Symbol", show=False),
        Binding("ctrl+2", "toggle_column('price')", "Col Price", show=False),
        Binding("ctrl+3", "toggle_column('chg')", "Col 1D%", show=False),
        Binding("ctrl+4", "toggle_column('pos')", "Col Pos", show=False),
        Binding("ctrl+5", "toggle_column('value')", "Col Value", show=False),
        Binding("ctrl+6", "toggle_column('cost')", "Col Cost", show=False),
        Binding("ctrl+7", "toggle_column('pnl')", "Col P&L%", show=False),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
        Binding("ctrl+c", "force_quit", "Quit", priority=True),
        Binding("ctrl+q", "force_quit", "Quit", priority=True),
        Binding("ctrl+n", "new_world", "New world"),
        Binding("ctrl+s", "save_game", "Save"),
        Binding("ctrl+l", "load_game", "Load"),
    ]

    def __init__(self, trader: TraderApp):
        super().__init__()
        self.trader = trader
        self.playing = False
        self.speed_idx = 0                   # default live-play speed: 1 sim-minute per real second
        self.view_source: list[str] | None = None    # None => holdings + watchlist; else full candidate list
        self.view_label = "watchlist"
        self.view_page = 0
        self.page_size = 25
        self.owned_only = False
        self.movers = False                  # movers view (top gainers/losers across the market)
        self.sort_by_change = False          # sort the board by 1D % instead of natural order
        self.col_visible = {cid: True for cid, _, _ in BOARD_COLUMNS}  # board columns shown (Ctrl+1..6)
        self.chart_range = 1                 # index into CHART_RANGES (default 1D)
        self.cursor_aid: str | None = None    # asset highlighted on the board (for the name line + chart)
        self.slot: str | None = None          # current manual save slot (Ctrl+S default)
        self.saves_dir = SAVES_DIR
        self.autosave_enabled = True
        self.resumed = False                  # set by run_tui when launched from an autosave
        self._last_autosave = 0.0
        self._play_clock: float | None = None   # monotonic ts of the last live-play advance; None while
        self._tick_accum = 0.0                  # paused/modal-open. accum carries fractional ticks/sec.
        self._ticker_base = ""               # cached marquee string; sliced each timer for the scroll
        self._ticker_off = 0
        notable = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "GOOGL", "TSLA"]
        w = trader.world
        self.watch: list[str] = [f"CRYPTO:{c.symbol}" for c in w.universe.crypto]
        for sym in notable:
            if w.has_asset(f"STOCK:{sym}"):
                self.watch.append(f"STOCK:{sym}")

    # ---- layout ---- #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(id="ticker")
        yield Static(id="status")
        with Horizontal(id="body"):
            yield DataTable(id="board", zebra_stripes=True, cursor_type="row")
            with Vertical(id="side"):
                yield Static(id="equity")
                yield Static(id="chart")
                yield Static(id="port")
                yield RichLog(id="log", wrap=True, markup=True)
        yield Input(placeholder="press : for a command  (buy BTR $500 · short SLR 50 · movers · find tesla · predict NVDA 1d · help)", id="cmd")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "TRADER PRO"
        self.sub_title = "◆ retro market terminal"
        table = self.query_one("#board", DataTable)
        table.add_columns(*[header for _, header, _ in self._visible_columns()])
        table.border_title = "MARKET · watchlist"
        self.query_one("#log", RichLog).border_title = "news & log"
        self.query_one("#equity", Static).border_title = "net worth"
        self.query_one("#chart", Static).border_title = "chart"
        self.set_focus(table)
        self.set_interval(0.3, self._on_timer)
        self._last_autosave = time.monotonic()
        self._log(Text("╔═ Welcome to TRADER PRO ═╗", style=f"bold {GREEN_HI}"))
        self._log(Text("Space=play  [ ]=speed  5=movers  o=sort  c=chart  Ctrl+S/L=save/load  :=cmd  ?=help",
                       style="bold cyan"))
        if self.resumed:
            w = self.trader.world
            nw = w.portfolio.net_worth(w.price_of)
            ret = (nw / w.config.starting_cash - 1) * 100
            self._log(Text(f"▶ Resumed your last game · {fmt_clock(w.market.tick_index)} · "
                           f"net worth {money(nw)} ({ret:+.1f}%)   (Ctrl+N for a new world)",
                           style="bold cyan"))
        self._refresh()

    # ---- live clock ---- #

    def _on_timer(self) -> None:
        # While a modal (Help / Trade / New-world) is up it owns the screen, so the base-screen
        # widgets (#ticker/#board/...) aren't queryable -- and the market effectively pauses.
        # Drop the play baseline so no real time is banked across the modal (or a pause).
        if len(self.screen_stack) > 1:
            self._play_clock = None
            return
        self._tick_ticker()                  # scroll the marquee even while paused
        if not self.playing:
            self._play_clock = None
            return
        # Advance the market by REAL elapsed time * the speed's ticks/second, so play runs at a
        # steady wall-clock pace (default 1 sim-minute per real second) regardless of timer jitter.
        now = time.monotonic()
        if self._play_clock is None:         # just (re)started playing -- set the baseline, no jump
            self._play_clock = now
            self._tick_accum = 0.0
            return
        elapsed = min(now - self._play_clock, 1.0)   # cap a single step so a stall (sleep/GC) can't fast-forward
        self._play_clock = now
        self._tick_accum += elapsed * SPEEDS[self.speed_idx][1]
        steps = int(self._tick_accum)
        if steps <= 0:                       # not a whole sim-minute yet; wait for more real time
            return
        self._tick_accum -= steps
        events, closures = self.trader._advance(steps)
        self._log_events(events)
        self._log_closures(closures)
        self._refresh()
        if self.autosave_enabled:
            if now - self._last_autosave >= AUTOSAVE_SECS:
                self._autosave()
                self._last_autosave = now

    def _log_events(self, events) -> None:
        for ev in events[:4]:
            style = "green" if ev.severity > 0 else "red"
            mark = "▲" if ev.severity > 0 else "▼"
            self._log(Text(f"{fmt_clock(ev.fire_tick)}  {mark} {ev.headline}", style=style))

    def _log_closures(self, closures) -> None:
        for c in closures:
            sym = c.order.asset_id.split(":", 1)[1]
            self._log(Text(f"⚠ MARGIN CALL — closed {c.order.quantity:g} {sym} "
                           f"@ {money(c.price)} (P&L {c.realized_pnl:+,.2f})", style="bold red"))

    # ---- shared math ---- #

    def _chg1d(self, aid: str) -> float:
        """1-day % change for an asset (price now vs one DAY ago)."""
        w, eng = self.trader.world, self.trader.engine
        t = w.market.tick_index
        price = w.price(aid)
        prev = eng.price_at(aid, max(0, t - DAY))
        return (price / prev - 1) * 100 if prev > 0 else 0.0

    def _movers(self, n: int = 10) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
        """(gainers, losers) — the n biggest 1D% up/down moves across the whole market."""
        w = self.trader.world
        rows = [(self._chg1d(aid), aid) for aid in w.asset_ids()]
        rows.sort(reverse=True)
        gainers = rows[:n]
        losers = rows[-n:][::-1]             # biggest loser first
        return gainers, losers

    # ---- ticker tape ---- #

    def _build_ticker(self) -> None:
        w = self.trader.world
        segs = []
        for aid in self.watch[:18]:
            if not w.has_asset(aid):
                continue
            chg = self._chg1d(aid)
            arr = "▲" if chg >= 0 else "▼"
            segs.append(f"{aid.split(':',1)[1]} {w.price(aid):,.2f} {arr}{abs(chg):.1f}%")
        self._ticker_base = "     ".join(segs) + "     " if segs else ""

    def _tick_ticker(self) -> None:
        base = self._ticker_base
        if not base:
            return
        self._ticker_off = (self._ticker_off + 1) % len(base)
        width = max(10, (self.size.width or 80) - 2)
        stream = base
        while len(stream) < self._ticker_off + width:
            stream += base
        view = stream[self._ticker_off:self._ticker_off + width]
        self.query_one("#ticker", Static).update(Text(view, style=f"bold {TICKER_COLOR}"))

    # ---- rendering ---- #

    def _visible(self) -> tuple[list[str], str | None]:
        """(asset_ids_to_show, next_row_label). Holdings of the current view pin to the top;
        then a page of `page_size` assets you don't own. A non-None label => add a Next row.
        With `sort_by_change` on, the candidate page is ordered by 1D % (descending)."""
        w = self.trader.world
        held = [a for a in w.portfolio.positions if w.has_asset(a)]
        if self.owned_only:
            if self.sort_by_change:
                held = sorted(held, key=self._chg1d, reverse=True)
            return held, None
        if self.view_source is None:
            seen, out = set(), []
            for aid in held + self.watch:
                if aid not in seen and w.has_asset(aid):
                    seen.add(aid); out.append(aid)
            if self.sort_by_change:
                out = sorted(out, key=self._chg1d, reverse=True)
            return out, None
        src = set(self.view_source)
        held = [a for a in held if a in src]
        owned = set(held)
        cands = [a for a in self.view_source if a not in owned and w.has_asset(a)]
        if self.sort_by_change:
            cands = sorted(cands, key=self._chg1d, reverse=True)
        if not cands:
            return held, None
        total = (len(cands) + self.page_size - 1) // self.page_size
        page = self.view_page % total
        page_ids = cands[page * self.page_size:(page + 1) * self.page_size]
        label = f"Next {self.page_size}   (page {page + 1}/{total})" if total > 1 else None
        return held + page_ids, label

    def _render_status(self) -> None:
        """Render the status block at the top of the screen. Its 4th row (otherwise blank) shows
        the full name of the asset currently highlighted on the board, so browsing the list tells
        you what each symbol is. Cheap enough to redraw on every cursor move."""
        w = self.trader.world
        pf = w.portfolio
        po = w.price_of
        t = w.market.tick_index
        nw = pf.net_worth(po)
        ret = (nw / w.config.starting_cash - 1) * 100
        speed = "PAUSED" if not self.playing else SPEEDS[self.speed_idx][0]
        status = Text()
        status.append("TRADER PRO ", style="bold cyan")
        status.append(f"seed {w.config.world_seed} · {w.config.profile} · "
                      f"fees {getattr(w.config, 'fee_level', 'off')} · {fmt_clock(t)}   ")
        status.append(f"[{speed}]\n", style="bold yellow" if self.playing else "dim")
        status.append(f"cash {money(pf.cash)}   equity {money(pf.equity(po))}   net worth {money(nw)} ")
        status.append(f"({ret:+.1f}%)\n", style="green" if ret >= 0 else "red")
        status.append(f"sentiment {w.market.sentiment:+.2f}   rate {w.market.interest_rate*100:.2f}%   "
                      f"buying power {money(pf.buying_power(po))}")
        if pf.loan_balance() > 0:
            status.append(f"   loans {money(pf.loan_balance())}", style="yellow")
        if pf.is_margin_call(po):
            status.append("   ⚠ MARGIN CALL", style="bold red")
        status.append("\n")
        aid = self.cursor_aid
        if aid and w.has_asset(aid):
            status.append("▶ ", style="bold cyan")
            status.append(f"{aid.split(':', 1)[1]}  ", style="bold")
            status.append(w.name_of(aid), style="white")
            status.append(f"   · {w.kind_of(aid).name.title()}", style="dim")
        self.query_one("#status", Static).update(status)

    def _render_chart(self) -> None:
        """Render the price-chart pane for the currently highlighted asset. Range is set by
        `chart_range` (1H/1D/3D/1W) and cycled with the `c` key. Sizes itself to the panel."""
        w, eng = self.trader.world, self.trader.engine
        panel = self.query_one("#chart", Static)
        aid = self.cursor_aid
        if not (aid and w.has_asset(aid)):
            panel.border_title = "chart"
            panel.update(Text("highlight an asset to chart it ▲▼", style="dim"))
            return
        label, span = CHART_RANGES[self.chart_range]
        cw = max(8, (panel.size.width or 28) - 4)
        ch = max(3, (panel.size.height or 10) - 3)
        t = w.market.tick_index
        start = max(0, t - span)
        step = max(1, span // cw)
        vals = [p for _, p in eng.series(aid, start, t + 1, step)]
        cur = w.price(aid)
        first = vals[0] if vals else cur
        chg = (cur / first - 1) * 100 if first else 0.0
        tone = "green" if chg >= 0 else "red"
        lo, hi = (min(vals), max(vals)) if vals else (cur, cur)
        panel.border_title = f"chart · {aid.split(':',1)[1]} {label}"
        body = area_chart(vals, cw, ch, tone)
        out = Text()
        out.append_text(body)
        out.append("\n")
        out.append(f"{money(cur)} ", style=f"bold {tone}")
        out.append(f"{chg:+.2f}%  ", style=tone)
        out.append(f"hi ${hi:,.0f} lo ${lo:,.0f}", style="dim")
        panel.update(out)

    def _visible_columns(self) -> list[tuple]:
        """The BOARD_COLUMNS currently shown, in fixed left-to-right order."""
        return [c for c in BOARD_COLUMNS if self.col_visible.get(c[0], True)]

    def _separator_row(self, table: DataTable, label: Text, key: str, *, hint_1d: bool = False) -> None:
        """A banner / pager row (movers headers, the 'Next page' row). Emits exactly one cell per
        *visible* column: the label in the first, blanks in the rest -- except the 1D% column keeps
        a dim '1D %' hint on the gainers header. Adapts as columns are toggled on/off."""
        cells: list[Text] = []
        for cid, _, _ in self._visible_columns():
            if not cells:
                cells.append(label)
            elif hint_1d and cid == "chg":
                cells.append(Text("1D %", style="dim", justify="right"))
            else:
                cells.append(Text(""))
        table.add_row(*cells, key=key)

    def _add_row(self, table: DataTable, aid: str) -> None:
        w, eng = self.trader.world, self.trader.engine
        pf = w.portfolio
        t = w.market.tick_index
        price = w.price(aid)
        prev = eng.price_at(aid, max(0, t - DAY))
        chg = (price / prev - 1) * 100 if prev > 0 else 0.0
        pos = pf.positions.get(aid)
        qty = pos.quantity if pos else 0.0
        cost = pos.avg_cost if pos else 0.0
        # Unrealized return if you closed the position now: +% when in profit, for longs and shorts
        # alike (a short profits as price falls). Fees are ignored, matching the side panel's P&L.
        pnl = (price - cost) / cost * 100 * (1.0 if qty >= 0 else -1.0) if (qty and cost) else 0.0
        ctx = _RowCtx(aid.split(":", 1)[1], price, chg, qty, qty * price, cost, pnl)
        table.add_row(*[render(ctx) for _, _, render in self._visible_columns()], key=aid)

    def _refresh(self, keep_row: bool = False) -> None:
        w = self.trader.world
        pf = w.portfolio
        po = w.price_of

        self._render_status()
        self._build_ticker()
        self._render_chart()

        table = self.query_one("#board", DataTable)
        # Remember which row is highlighted so advancing time (s/h/d), live play, or a trade
        # doesn't snap the selection back to the top when the board is rebuilt below.
        prev_key = None
        if table.row_count:
            try:
                prev_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                prev_key = None
        prev_row = table.cursor_row
        table.clear()
        row_keys: list[str] = []
        if self.movers:
            table.border_title = "MARKET · movers"
            gainers, losers = self._movers(10)
            self._separator_row(table, Text("▲ TOP GAINERS", style="bold green"), "__hdr_g__", hint_1d=True)
            row_keys.append("__hdr_g__")
            for _, aid in gainers:
                self._add_row(table, aid); row_keys.append(aid)
            self._separator_row(table, Text("▼ TOP LOSERS", style="bold red"), "__hdr_l__")
            row_keys.append("__hdr_l__")
            for _, aid in losers:
                self._add_row(table, aid); row_keys.append(aid)
        else:
            sort_tag = "  ↓%" if self.sort_by_change else ""
            table.border_title = f"MARKET · {self.view_label}{sort_tag}"
            ids, next_label = self._visible()
            for aid in ids:
                self._add_row(table, aid); row_keys.append(aid)
            if next_label:
                self._separator_row(table, Text("→ " + next_label, style="bold cyan"), "__next__")
                row_keys.append("__next__")
        # Restore the highlight. By default we re-find the same *asset*, so advancing time or
        # live play doesn't snap the cursor around. After a trade (`keep_row`) we instead hold
        # the same *row*: buying pins the asset into the holdings block at the top, and we don't
        # want that to yank the highlight up to row 0 -- you keep your place in the list.
        if keep_row and row_keys:
            target = min(prev_row, len(row_keys) - 1)
        elif prev_key is not None and prev_key in row_keys:
            target = row_keys.index(prev_key)
        elif row_keys:
            target = min(prev_row, len(row_keys) - 1)
        else:
            target = -1
        if target >= 0 and target != table.cursor_row:
            try:
                table.move_cursor(row=target)
            except Exception:
                pass
        # After a trade the row we land on is usually a *different* asset than the one we traded
        # (the traded asset jumped into the holdings block), so re-sync the name line + chart to
        # whatever is under the cursor now.
        if keep_row and target >= 0:
            landed = row_keys[target]
            self.cursor_aid = landed if w.has_asset(landed) else None
            self._render_status()
            self._render_chart()

        port = Text()
        if not pf.positions:
            port.append("No open positions.\n", style="dim")
        else:
            port.append("POSITIONS\n", style="bold")
            for aid, pos in pf.positions.items():
                price = w.price(aid)
                pnl = (price - pos.avg_cost) * pos.quantity
                tag = " SHORT" if pos.quantity < 0 else ""
                port.append(f"  {aid.split(':',1)[1]:<10}{pos.quantity:>9g}{tag}\n",
                            style="yellow" if pos.quantity < 0 else "")
                port.append(f"    @{money(pos.avg_cost)} ", style="dim")
                port.append(f"{pnl:+,.2f}\n", style="green" if pnl >= 0 else "red")
        port.append(f"\nrealized P&L {money(pf.realized_pnl)}", style="dim")
        self.query_one("#port", Static).update(port)

        hist = pf.nw_history
        eq = Text()
        if len(hist) >= 2:
            vals = [v for _, v in hist]
            width = 28
            if len(vals) > width:
                step = len(vals) / width
                disp = [vals[min(len(vals) - 1, int(i * step))] for i in range(width)]
                disp[-1] = vals[-1]
            else:
                disp = vals
            cur, lo, hi = vals[-1], min(vals), max(vals)
            ret = (cur / w.config.starting_cash - 1) * 100
            tone = "green" if ret >= 0 else "red"
            eq.append(f"{money(cur)}  ", style="bold " + tone)
            eq.append(f"{ret:+.1f}%\n", style=tone)
            eq.append(sparkline(disp) + "\n", style=tone)
            eq.append(f"hi ${hi:,.0f}  lo ${lo:,.0f}  · {len(hist)}p", style="dim")
        else:
            eq.append("NET WORTH\n", style="bold")
            eq.append("play the clock ▶ to chart it", style="dim")
        self.query_one("#equity", Static).update(eq)

    def _log(self, renderable) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _log_ansi(self, text: str) -> None:
        if text:
            self.query_one("#log", RichLog).write(Text.from_ansi(text))

    # ---- actions ---- #

    def action_force_quit(self) -> None:
        self._autosave()
        self.exit()

    def action_quit(self) -> None:
        self._autosave()
        self.exit()

    def _autosave(self) -> None:
        if not self.autosave_enabled:
            return
        try:
            save_game(self.trader.world, autosave_path(self.saves_dir), label=AUTOSAVE_SLOT)
        except Exception:
            pass

    def action_save_game(self) -> None:
        self.push_screen(SaveScreen(self.slot or "save"), self._on_save_dismissed)

    def _on_save_dismissed(self, name) -> None:
        if name:
            self._do_save(name)

    def action_load_game(self) -> None:
        infos = list_saves(self.saves_dir)
        if not infos:
            self._log(Text("no saves yet — Ctrl+S to save one", style="yellow"))
            return
        self.push_screen(LoadScreen(infos, self.saves_dir), self._on_load_dismissed)

    def _on_load_dismissed(self, name) -> None:
        if name:
            self._do_load(name)

    def _do_save(self, name: str) -> None:
        name = re.sub(r"[^A-Za-z0-9_-]", "", name).strip("-_") or "save"
        try:
            meta = save_game(self.trader.world, slot_path(name, self.saves_dir), label=name)
        except Exception as exc:
            self._log(Text(f"save failed: {exc}", style="red"))
            return
        self.slot = name
        self._log(Text(f"▶ saved → {name} · net worth {money(meta['net_worth'])} "
                       f"({meta['return_pct']:+.1f}%)", style="cyan"))

    def _do_load(self, name: str) -> None:
        path = slot_path(name, self.saves_dir)
        if not path.exists():
            self._log(Text(f"no save named {name}", style="yellow"))
            return
        try:
            world = load_game(path, self.trader.universe)
        except Exception as exc:
            self._log(Text(f"could not load {name}: {exc}", style="red"))
            return
        self.trader.start_world(world)
        self.slot = None if name == AUTOSAVE_SLOT else name
        nw = world.portfolio.net_worth(world.price_of)
        ret = (nw / world.config.starting_cash - 1) * 100
        self.query_one("#log", RichLog).clear()
        self._log(Text(f"◀ loaded {name} · {fmt_clock(world.market.tick_index)} · "
                       f"net worth {money(nw)} ({ret:+.1f}%)", style="bold cyan"))
        self._reset_view_after_swap()

    def action_toggle_play(self) -> None:
        self.playing = not self.playing
        self._refresh()

    def action_faster(self) -> None:
        self.speed_idx = min(self.speed_idx + 1, len(SPEEDS) - 1)
        self._refresh()

    def action_slower(self) -> None:
        self.speed_idx = max(self.speed_idx - 1, 0)
        self._refresh()

    def action_step(self) -> None:
        self.trader._advance(1); self._refresh()

    def action_hour(self) -> None:
        ev, clo = self.trader._advance(HOUR)
        self._log_events(ev); self._log_closures(clo); self._refresh()

    def action_day(self) -> None:
        ev, clo = self.trader._advance(DAY)
        self._log_events(ev); self._log_closures(clo); self._refresh()

    def action_command(self) -> None:
        self.set_focus(self.query_one("#cmd", Input))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_chart_range(self) -> None:
        self.chart_range = (self.chart_range + 1) % len(CHART_RANGES)
        self._render_chart()

    def action_toggle_column(self, cid: str) -> None:
        """Show/hide a board column (Ctrl+1..Ctrl+7). Session-only -- resets to all-on next launch.
        Refuses to hide the last remaining column so the board never ends up with zero columns."""
        # A modal owns the screen while it's open (the board isn't queryable) -- ignore the key.
        if len(self.screen_stack) > 1 or cid not in self.col_visible:
            return
        header = next(h for i, h, _ in BOARD_COLUMNS if i == cid)
        if self.col_visible[cid] and sum(self.col_visible.values()) == 1:
            self._log(Text(f"can't hide '{header}' — it's the last visible column", style="yellow"))
            return
        self.col_visible[cid] = not self.col_visible[cid]
        self._rebuild_board_columns()
        self._log(Text(f"column '{header}' " + ("shown" if self.col_visible[cid] else "hidden"),
                       style="cyan"))

    def _rebuild_board_columns(self) -> None:
        """Re-create the board's columns from `col_visible` and repaint. A DataTable can't hide a
        column in place, so we drop columns+rows and rebuild; _refresh re-adds the rows. We hold the
        highlighted asset across the rebuild (consistent with how trades/time-advance keep the row)."""
        table = self.query_one("#board", DataTable)
        prev_key = None
        if table.row_count:
            try:
                prev_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                prev_key = None
        table.clear(columns=True)
        table.add_columns(*[header for _, header, _ in self._visible_columns()])
        self._refresh()
        if prev_key is not None:
            try:
                table.move_cursor(row=table.get_row_index(prev_key))
            except Exception:
                pass

    def action_toggle_sort(self) -> None:
        self.sort_by_change = not self.sort_by_change
        self.view_page = 0
        self._log(Text("sort → " + ("1D % (high→low)" if self.sort_by_change else "default order"),
                       style="dim"))
        self._refresh()
        try:
            self.query_one("#board", DataTable).move_cursor(row=0)
        except Exception:
            pass

    def action_view_movers(self) -> None:
        self.movers = True
        self.owned_only = False
        self.view_source = None
        self.view_label = "movers"
        self._log(Text("board → movers (top gainers & losers)", style="dim"))
        self._refresh()
        try:
            self.query_one("#board", DataTable).move_cursor(row=1)
        except Exception:
            pass

    def action_new_world(self) -> None:
        self.push_screen(NewWorldScreen(), self._on_new_world)

    def _on_new_world(self, result) -> None:
        if not result:
            return
        profile, seed, cash, fee_level = result
        world = World.new(self.trader.universe, world_seed=seed, profile=profile,
                          starting_cash=cash, fee_level=fee_level)
        self.trader.start_world(world)
        self.slot = None
        self.query_one("#log", RichLog).clear()
        self._log(Text(f"★ new world  ·  seed {seed} · {profile} · "
                       f"{money(cash)} · fees {fee_level}", style="bold cyan"))
        self._reset_view_after_swap()

    def _reset_view_after_swap(self) -> None:
        """Reset all view state after a world swap (new world / load), then redraw + home."""
        self.view_source = None
        self.view_label = "watchlist"
        self.view_page = 0
        self.owned_only = False
        self.movers = False
        self.sort_by_change = False
        self.cursor_aid = None
        self.playing = False
        self._refresh()
        board = self.query_one("#board", DataTable)
        self.set_focus(board)
        try:
            board.move_cursor(row=0)
        except Exception:
            pass

    def action_view_crypto(self) -> None:
        self._set_view(self._kind_ids(AssetKind.CRYPTO), "crypto")

    def action_view_stocks(self) -> None:
        self._set_view(self._kind_ids(AssetKind.STOCK), "stocks")

    def action_view_bonds(self) -> None:
        self._set_view(self._kind_ids(AssetKind.BOND), "bonds")

    def action_view_watch(self) -> None:
        self._set_view(None, "watchlist")

    def action_view_owned(self) -> None:
        self._set_view(None, "owned")
        self.owned_only = True
        self._refresh()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if len(self.screen_stack) > 1:        # event bubbled up from a modal's table
            return
        aid = event.row_key.value
        if aid == "__next__":
            self.view_page += 1
            self._refresh()
            try:
                self.query_one("#board", DataTable).move_cursor(row=0)
            except Exception:
                pass
            return
        if aid and self.trader.world.has_asset(aid):
            self.push_screen(TradeDialog(aid), self._on_trade_closed)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if len(self.screen_stack) > 1:        # event bubbled up from a modal's table
            return
        key = getattr(event.row_key, "value", None)
        w = self.trader.world
        self.cursor_aid = key if (key and w.has_asset(key)) else None
        self._render_status()
        self._render_chart()

    def _on_trade_closed(self, result) -> None:
        """Runs on the app after a TradeDialog pops. `result` is None on cancel, else
        (verb, qty, sym, ExecutionResult). Log + redraw here, on the main screen once the modal
        is gone, so the dialog never touches our widgets while it is still open."""
        if result is not None:
            verb, qty, sym, res = result
            fee_txt = f" fee {money(res.fee)}" if getattr(res, "fee", 0) else ""
            self._log(Text(f"{verb} {qty:g} {sym} @ {money(res.price)}{fee_txt} "
                           f"(P&L {res.realized_pnl:+,.2f})", style="green"))
        self._refresh(keep_row=result is not None)

    # ---- view switching ---- #

    def _set_view(self, source: list[str] | None, label: str) -> None:
        self.view_source = source
        self.view_label = label
        self.view_page = 0
        self.owned_only = False
        self.movers = False
        self._log(Text(f"board → {label}", style="dim"))
        self._refresh()
        try:
            self.query_one("#board", DataTable).move_cursor(row=0)
        except Exception:
            pass

    def _kind_ids(self, kind: AssetKind) -> list[str]:
        w = self.trader.world
        return [a for a in w.asset_ids() if w.kind_of(a) is kind]

    def _show_look(self, args) -> None:
        if not args:
            self._log(Text("usage: look <SYM>", style="yellow")); return
        aid = self.trader.resolve(args[0])
        if not aid:
            self._log(Text(f"unknown symbol {args[0]!r}", style="yellow")); return
        w, eng = self.trader.world, self.trader.engine
        t = w.market.tick_index
        price = w.price(aid)
        h1 = eng.price_at(aid, max(0, t - HOUR)); d1 = eng.price_at(aid, max(0, t - DAY))
        path = [eng.price_at(aid, max(0, t - 3 * DAY + i * (3 * DAY // 24))) for i in range(24)]
        ch1 = (price / h1 - 1) * 100 if h1 else 0.0
        chd = (price / d1 - 1) * 100 if d1 else 0.0
        txt = Text()
        txt.append(f"{aid.split(':',1)[1]}  {w.name_of(aid)}\n", style="bold")
        txt.append(f"  {money(price)}   ")
        txt.append(f"1h {ch1:+.2f}%  ", style="green" if ch1 >= 0 else "red")
        txt.append(f"1d {chd:+.2f}%\n", style="green" if chd >= 0 else "red")
        txt.append(f"  {sparkline(path)}", style="cyan")
        self._log(txt)

    # ---- command input ---- #

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd":
            return
        line = event.value.strip()
        event.input.value = ""
        self.set_focus(self.query_one("#board", DataTable))
        if not line:
            return
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]

        if cmd in ("play", "pause"):
            self.action_toggle_play(); return
        if cmd == "faster":
            self.action_faster(); return
        if cmd == "slower":
            self.action_slower(); return
        if cmd == "run":
            self.playing = True; self._log(Text("▶ live (Space to pause)", style="cyan"))
            self._refresh(); return
        if cmd in ("quit", "exit"):
            self.action_quit(); return
        if cmd in ("help", "?"):
            self.push_screen(HelpScreen()); return
        if cmd == "clear":
            self.query_one("#log", RichLog).clear(); return
        if cmd == "save":
            self._do_save(args[0] if args else (self.slot or "save")); return
        if cmd == "load":
            if args:
                self._do_load(args[0])
            else:
                self.action_load_game()
            return
        if cmd in ("saves", "slots"):
            self.action_load_game(); return
        if cmd in ("port", "portfolio", "p"):
            self._log(Text("(your positions & P&L are in the panel above)", style="dim"))
            self._refresh(); return

        # board views
        if cmd == "market":
            self._set_view(None, "watchlist"); return
        if cmd == "watch":
            if args:
                aid = self.trader.resolve(args[0])
                if aid and aid not in self.watch:
                    self.watch.append(aid)
            self._set_view(None, "watchlist"); return
        if cmd in ("stocks", "stock"):
            self._set_view(self._kind_ids(AssetKind.STOCK), "stocks"); return
        if cmd == "bonds":
            self._set_view(self._kind_ids(AssetKind.BOND), "bonds"); return
        if cmd == "crypto":
            self._set_view(self._kind_ids(AssetKind.CRYPTO), "crypto"); return
        if cmd == "movers":
            self.action_view_movers(); return
        if cmd == "sort":
            self.action_toggle_sort(); return
        if cmd == "find":
            if not args:
                self._log(Text("usage: find <text>", style="yellow")); return
            q = " ".join(args).lower()
            w = self.trader.world
            ids = [a for a in w.asset_ids()
                   if q in w.name_of(a).lower() or q in a.split(":", 1)[1].lower()]
            self._set_view(ids, f"find '{q}' ({len(ids)})"); return
        if cmd in ("look", "l"):
            self._show_look(args); return

        # everything else -> core logic, short confirmation to the log
        self._log_ansi(self.trader.execute(line))
        self._refresh(keep_row=cmd in ("buy", "sell", "short", "cover"))


def textual_version_ok() -> tuple[bool, str]:
    """(supported, version). The TradeDialog modal deadlocks Textual's screen teardown on
    >= 0.72 — you trade, the dialog closes, and the whole TUI locks up (Ctrl-C included) while
    the background ticker keeps scrolling. See docs/freeze-bug/README.md. 0.71.x is the last
    good release, so we require < 0.72."""
    import textual
    v = getattr(textual, "__version__", "0")
    nums = []
    for part in v.split(".")[:2]:
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        nums.append(int(digits) if digits else 0)
    while len(nums) < 2:
        nums.append(0)
    return tuple(nums[:2]) < (0, 72), v


def run_tui() -> None:
    ok, ver = textual_version_ok()
    if not ok:
        print(
            "\n  ⚠  Trader PRO needs Textual < 0.72 — you have "
            + ver + ".\n"
            "     Textual 0.72+ has a regression that FREEZES the trade dialog on close:\n"
            "     you buy something, the dialog disappears, then the whole TUI locks up\n"
            "     (the ticker keeps scrolling, but no keys work — not even Ctrl-C).\n\n"
            "     Fix it with:\n"
            "         pip install \"textual<0.72\"\n\n"
            "     (background: docs/freeze-bug/README.md)\n"
        )
        return
    universe = load_seed_universe()
    world = None
    resumed = False
    if has_autosave():
        try:
            world = load_game(autosave_path(), universe)
            resumed = True
        except Exception:
            world = None
    if world is None:
        world = World.new(universe, world_seed=20260614, profile="Normal",
                          starting_cash=5000.0, fee_level="off")
    trader = TraderApp(world, universe=universe)
    app = TraderTUI(trader)
    app.resumed = resumed
    app.run()


if __name__ == "__main__":
    run_tui()
