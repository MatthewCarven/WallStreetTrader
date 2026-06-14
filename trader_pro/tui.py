"""Textual TUI front-end for Trader PRO — the retro live-market client.

    python play_tui.py        # or:  python -m trader_pro.tui

Wraps the same `TraderApp` logic the CLI uses, but the market *ticks live*. Browse commands
(stocks/crypto/bonds/find) repopulate the main board; trades/loans/predictions print a short
line to the news log; `help` and `look` open a panel. Requires `textual`.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static
from rich.text import Text

from .cli import TraderApp
from .core import AssetKind, Order, OrderSide, World, execute_order, load_seed_universe
from .core.engine import DAY, HOUR

SPEEDS = [("Slow", 1), ("Normal", 12), ("Fast", 90), ("Turbo", 600)]
SPARK = "▁▂▃▄▅▆▇█"


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


HELP_TEXT = """[b cyan]Trader PRO — TUI help[/]

[b]Keys[/]
  Space   play / pause the live clock
  0 1 2 3 4 view owned / crypto / stocks / bonds / watchlist
  Enter   open a buy/sell dialog for the highlighted row
  [  ]     slower / faster   (Slow → Turbo)
  s        step one minute      h  +1 hour      d  +1 day
  :        open the command line
  q        quit

[b]Command line[/]  (press : first)
  [b]Browse[/] (fills the board):
    market            your holdings + watchlist
    stocks [n]        first n stocks (default 25)
    crypto / bonds    list a class
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
    save [name]       load [name]       clear   (clear the log)

[dim]press Esc or q to close[/]"""


class HelpScreen(ModalScreen):
    CSS = """
    HelpScreen { align: center middle; }
    #help-box { width: 78; height: 90%; border: round $primary; background: $panel; padding: 1 2; }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

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
    BINDINGS = [("escape", "cancel", "Cancel")]

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
        token = self.query_one("#qty", Input).value.strip()
        if not token:                      # empty box: do nothing (no accidental orders)
            self._msg("enter a quantity first (e.g. 10, $500, or all)", "yellow")
            return
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
        sym = self.aid.split(":", 1)[1]
        if res.filled:
            self.app._log(Text(f"{verb} {qty:g} {sym} @ {money(res.price)} "
                               f"(P&L {res.realized_pnl:+,.2f})", style="green"))
            self.app._refresh()
            self._close()
        else:
            self._msg(res.message, "red")
            self.app._refresh()

    def _msg(self, text: str, style: str) -> None:
        self.query_one("#trade-msg", Static).update(Text(text, style=style))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._act(event.button.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._act("buy")

    def _close(self) -> None:
        """Dismiss at most once, even if extra key/clicks are queued."""
        if self._closing:
            return
        self._closing = True
        if self in self.app.screen_stack:
            self.dismiss()

    def action_cancel(self) -> None:
        self._close()


class TraderTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #status { height: 4; padding: 0 1; background: $panel; }
    #body { height: 1fr; }
    #board { width: 2fr; border: round $primary; }
    #side { width: 1fr; }
    #port { height: 1fr; padding: 0 1; background: $panel; }
    #log { height: 1fr; border: round $primary; overflow-x: hidden; }
    #cmd { dock: bottom; }
    DataTable { height: 1fr; }
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
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, trader: TraderApp):
        super().__init__()
        self.trader = trader
        self.playing = False
        self.speed_idx = 1
        self.view_source: list[str] | None = None    # None => holdings + watchlist; else full candidate list
        self.view_label = "watchlist"
        self.view_page = 0
        self.page_size = 25
        self.owned_only = False
        notable = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "GOOGL", "TSLA"]
        w = trader.world
        self.watch: list[str] = [f"CRYPTO:{c.symbol}" for c in w.universe.crypto]
        for sym in notable:
            if w.has_asset(f"STOCK:{sym}"):
                self.watch.append(f"STOCK:{sym}")

    # ---- layout ---- #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(id="status")
        with Horizontal(id="body"):
            yield DataTable(id="board", zebra_stripes=True, cursor_type="row")
            with Vertical(id="side"):
                yield Static(id="port")
                yield RichLog(id="log", wrap=True, markup=True)
        yield Input(placeholder="press : for a command  (buy BTR $500 · short SLR 50 · stocks · find tesla · predict NVDA 1d · help)", id="cmd")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#board", DataTable)
        table.add_columns("Symbol", "Price", "1D %", "Pos", "Value")
        table.border_title = "MARKET · watchlist"
        self.query_one("#log", RichLog).border_title = "news & log"
        self.set_focus(table)
        self.set_interval(0.3, self._on_timer)
        self._log(Text("Welcome to Trader PRO.  Space=play  [ ]=speed  :=command  ?=help", style="bold cyan"))
        self._refresh()

    # ---- live clock ---- #

    def _on_timer(self) -> None:
        if not self.playing:
            return
        events, closures = self.trader._advance(SPEEDS[self.speed_idx][1])
        self._log_events(events)
        self._log_closures(closures)
        self._refresh()

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

    # ---- rendering ---- #

    def _visible(self) -> tuple[list[str], str | None]:
        """(asset_ids_to_show, next_row_label). Holdings of the current view pin to the top;
        then a page of `page_size` assets you don't own. A non-None label => add a Next row."""
        w = self.trader.world
        held = [a for a in w.portfolio.positions if w.has_asset(a)]
        if self.owned_only:
            return held, None
        if self.view_source is None:
            seen, out = set(), []
            for aid in held + self.watch:
                if aid not in seen and w.has_asset(aid):
                    seen.add(aid); out.append(aid)
            return out, None
        src = set(self.view_source)
        held = [a for a in held if a in src]
        owned = set(held)
        cands = [a for a in self.view_source if a not in owned and w.has_asset(a)]
        if not cands:
            return held, None
        total = (len(cands) + self.page_size - 1) // self.page_size
        page = self.view_page % total
        page_ids = cands[page * self.page_size:(page + 1) * self.page_size]
        label = f"Next {self.page_size}   (page {page + 1}/{total})" if total > 1 else None
        return held + page_ids, label

    def _refresh(self) -> None:
        w = self.trader.world
        pf = w.portfolio
        po = w.price_of
        t = w.market.tick_index
        eng = self.trader.engine

        nw = pf.net_worth(po)
        ret = (nw / w.config.starting_cash - 1) * 100
        speed = "PAUSED" if not self.playing else SPEEDS[self.speed_idx][0]
        status = Text()
        status.append("TRADER PRO ", style="bold cyan")
        status.append(f"seed {w.config.world_seed} · {w.config.profile} · {fmt_clock(t)}   ")
        status.append(f"[{speed}]\n", style="bold yellow" if self.playing else "dim")
        status.append(f"cash {money(pf.cash)}   equity {money(pf.equity(po))}   net worth {money(nw)} ")
        status.append(f"({ret:+.1f}%)\n", style="green" if ret >= 0 else "red")
        status.append(f"sentiment {w.market.sentiment:+.2f}   rate {w.market.interest_rate*100:.2f}%   "
                      f"buying power {money(pf.buying_power(po))}")
        if pf.loan_balance() > 0:
            status.append(f"   loans {money(pf.loan_balance())}", style="yellow")
        if pf.is_margin_call(po):
            status.append("   ⚠ MARGIN CALL", style="bold red")
        self.query_one("#status", Static).update(status)

        table = self.query_one("#board", DataTable)
        table.border_title = f"MARKET · {self.view_label}"
        table.clear()
        ids, next_label = self._visible()
        for aid in ids:
            price = w.price(aid)
            prev = eng.price_at(aid, max(0, t - DAY))
            chg = (price / prev - 1) * 100 if prev > 0 else 0.0
            pos = pf.positions.get(aid)
            qty = pos.quantity if pos else 0.0
            table.add_row(
                Text(aid.split(":", 1)[1], style="bold"),
                Text(money(price), justify="right"),
                Text(f"{chg:+.2f}%", style="green" if chg >= 0 else "red", justify="right"),
                Text(f"{qty:g}" if qty else "·", justify="right",
                     style="yellow" if qty < 0 else ("white" if qty else "dim")),
                Text(money(qty * price) if qty else "", justify="right"),
                key=aid,
            )
        if next_label:
            table.add_row(Text("\u2192 " + next_label, style="bold cyan"),
                          Text(""), Text(""), Text(""), Text(""), key="__next__")

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

    def _log(self, renderable) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _log_ansi(self, text: str) -> None:
        if text:
            self.query_one("#log", RichLog).write(Text.from_ansi(text))

    # ---- actions ---- #

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
            self.push_screen(TradeDialog(aid))

    # ---- view switching ---- #

    def _set_view(self, source: list[str] | None, label: str) -> None:
        self.view_source = source
        self.view_label = label
        self.view_page = 0
        self.owned_only = False
        self._log(Text(f"board → {label}", style="dim"))
        self._refresh()

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
            self.exit(); return
        if cmd in ("help", "?"):
            self.push_screen(HelpScreen()); return
        if cmd == "clear":
            self.query_one("#log", RichLog).clear(); return
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
        self._refresh()


def run_tui() -> None:
    universe = load_seed_universe()
    trader = TraderApp(World.new(universe, world_seed=20260614, profile="Normal",
                                 starting_cash=2500.0), universe=universe)
    TraderTUI(trader).run()


if __name__ == "__main__":
    run_tui()
