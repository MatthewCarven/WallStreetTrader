"""Interactive terminal client — the first playable Trader PRO (V1.1).

Run it:
    python -m trader_pro            # or:  python play.py

The command logic lives in `TraderApp.execute(line) -> str`, which is pure and testable.
`repl()` is the thin interactive loop on top of it.

Design references: design.md §5.5 (speed control), §8.1 (UI surface), §8.2 (loans — stub
hook here, full system in V1.5).
"""

from __future__ import annotations

import shlex
import sys
import time
from pathlib import Path

from .core import (
    load_seed_universe, World, MarketEngine, AssetKind, make_asset_id,
    Order, OrderSide, execute_order, liquidate_for_margin, make_prediction, save_world, load_world,
    PROFILE_NAMES, get_profile,
)
from .core.engine import DAY, HOUR
from .errlog import log_error, setup_logging
from .fmt import money, fmt_qty
from .persistence import SAVES_DIR, save_game, load_game, slot_path, autosave_path

ROOT = Path(__file__).resolve().parents[1]
SPARK = "▁▂▃▄▅▆▇█"


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #

class C:
    GREEN = "\033[32m"; RED = "\033[31m"; DIM = "\033[2m"
    BOLD = "\033[1m"; CYAN = "\033[36m"; YELLOW = "\033[33m"; RESET = "\033[0m"


def _color_enabled() -> bool:
    return sys.stdout.isatty()


def col(s: str, c: str) -> str:
    return f"{c}{s}{C.RESET}" if _color_enabled() else s


def signed_pct(p0: float, p1: float) -> str:
    if p0 <= 0:
        return "  --  "
    p = (p1 / p0 - 1) * 100
    s = f"{p:+.2f}%"
    return col(s, C.GREEN if p >= 0 else C.RED) if _color_enabled() else s


def fmt_clock(t: int) -> str:
    d = t // DAY; h = (t % DAY) // HOUR; m = t % HOUR
    return f"D{d} {h:02d}:{m:02d}"


def sparkline(vals: list[float]) -> str:
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return SPARK[0] * len(vals)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #

class TraderApp:
    def __init__(self, world: World | None = None, *, universe=None):
        self.universe = universe or load_seed_universe()
        self.world = world or World.new(self.universe, world_seed=20260614, profile="Normal")
        self.engine = MarketEngine(self.world)
        self.running = True
        if not self.world.portfolio.nw_history:    # seed the equity chart at the current tick
            self.world.portfolio.record_net_worth(self.world.market.tick_index, self.world.price_of)

    def start_world(self, world: "World") -> None:
        """Swap in a fresh world (the TUI's Ctrl+N 'new world'): rebuild the engine and seed the
        equity chart, exactly like construction."""
        self.world = world
        self.engine = MarketEngine(world)
        if not world.portfolio.nw_history:
            world.portfolio.record_net_worth(world.market.tick_index, world.price_of)

    # ---- symbol resolution ---- #

    def resolve(self, token: str) -> str | None:
        token = token.strip().upper()
        for kind in (AssetKind.STOCK, AssetKind.CRYPTO, AssetKind.BOND):
            aid = make_asset_id(kind, token)
            if self.world.has_asset(aid):
                return aid
        if self.world.has_asset(token):       # already a full id
            return token
        return None

    # ---- the dashboard header ---- #

    def header(self) -> str:
        w = self.world; pf = w.portfolio; po = w.price_of
        eq = w.equity()
        ret = (eq / w.config.starting_cash - 1) * 100
        rets = col(f"{ret:+.1f}%", C.GREEN if ret >= 0 else C.RED)
        bar = col("TRADER PRO", C.BOLD + C.CYAN)
        nw = pf.net_worth(po)
        nwret = (nw / w.config.starting_cash - 1) * 100
        nwrets = col(f"{nwret:+.1f}%", C.GREEN if nwret >= 0 else C.RED)
        line3 = f"  net worth {money(nw)} ({nwrets})   buying power {money(pf.buying_power(po))}"
        if pf.loan_balance() > 0:
            line3 += f"   loans {money(pf.loan_balance())}"
        if pf.margin_debt() > 0:
            line3 += f"   margin debt {money(pf.margin_debt())}"
        if pf.is_margin_call(po):
            line3 += col("   ⚠ MARGIN CALL", C.RED)
        return (
            f"{bar}  seed {w.config.world_seed} · {w.config.profile} · {fmt_clock(w.market.tick_index)}\n"
            f"  cash {money(pf.cash)}   equity {money(eq)}   "
            f"return {rets}   sentiment {w.market.sentiment:+.2f}   rate {w.market.interest_rate*100:.2f}%\n"
            + line3
        )

    # ---- rendering an asset row ---- #

    def _row(self, aid: str) -> str:
        t = self.world.market.tick_index
        price = self.world.price(aid)
        day_ago = self.engine.price_at(aid, max(0, t - DAY))
        spark = sparkline([self.engine.price_at(aid, max(0, t - DAY + i * (DAY // 16))) for i in range(16)])
        sym = aid.split(":", 1)[1]
        return (f"  {sym:<11} {money(price):>14}  {signed_pct(day_ago, price):>16}  "
                f"{col(spark, C.DIM)}  {self.world.name_of(aid)[:24]}")

    def _list_kind(self, kind: AssetKind, n: int) -> str:
        ids = [a for a in self.world.asset_ids() if self.world.kind_of(a) is kind][:n]
        head = f"  {'SYMBOL':<11} {'PRICE':>14}  {'1D':>9}  {'~24h':<16}  NAME"
        return col(head, C.DIM) + "\n" + "\n".join(self._row(a) for a in ids)

    # ---- command dispatch ---- #

    def execute(self, line: str) -> str:
        line = line.strip()
        if not line:
            return ""
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]

        handler = {
            "help": self._help, "?": self._help,
            "market": self._market, "m": self._market,
            "stocks": lambda a: self._kind_cmd(AssetKind.STOCK, a),
            "bonds": lambda a: self._kind_cmd(AssetKind.BOND, a),
            "crypto": lambda a: self._kind_cmd(AssetKind.CRYPTO, a),
            "find": self._find,
            "look": self._look, "l": self._look,
            "buy": self._buy, "b": self._buy,
            "sell": self._sell, "s": self._sell,
            "short": self._short,
            "cover": self._cover,
            "port": self._port, "portfolio": self._port, "p": self._port,
            "news": self._news,
            "loan": self._loan,
            "fees": self._fees, "fee": self._fees,
            "repay": self._repay,
            "predict": self._predict, "pred": self._predict,
            "next": self._next, "n": self._next,
            "step": lambda a: self._next(["1"]),
            "hour": lambda a: self._next([str(HOUR)]),
            "day": lambda a: self._next([str(DAY)]),
            "run": self._run,
            "save": self._save, "load": self._load,
            "quit": self._quit, "exit": self._quit, "q": self._quit,
        }.get(cmd)

        if handler is None:
            return col(f"unknown command {cmd!r} — type 'help'", C.YELLOW)
        try:
            return handler(args)
        except (KeyboardInterrupt, SystemExit):
            raise                                       # let Ctrl-C / exit through to the REPL
        except Exception as exc:                        # a bug in one command must not kill the session
            log_error(exc, f"command {cmd!r}")
            return col(f"⚠ '{cmd}' hit an unexpected error — logged to logs/trader_pro.log, "
                       f"your game is unharmed. Type 'help' for commands.", C.RED)

    # ---- individual commands ---- #

    def _help(self, args) -> str:
        return (
            "commands:\n"
            "  market | m                overview: your holdings + the crypto board\n"
            "  stocks [n] | bonds | crypto [n]   list a kind\n"
            "  find <text>               search stocks/assets by name or symbol\n"
            "  look <SYM> | l            asset detail + recent path\n"
            "  buy  <SYM> <qty|$amount>  e.g. 'buy AAPL 10' or 'buy BTR $500'\n"
            "  sell <SYM> <qty|all>      e.g. 'sell AAPL 5' or 'sell BTR all'\n"
            "  short <SYM> <qty|$amt>    open/extend a short (profit if it falls)\n"
            "  cover <SYM> [qty|all]     buy back a short\n"
            "  (buying uses up to 2:1 margin; shorts & leverage can trigger margin calls)\n"
            "  port | p                  your portfolio & P&L\n"
            "  news                      recent market headlines\n"
            "  predict <SYM> [1d|6h]     buy a forecast (accuracy depends on the world)\n"
            "  loan <amount>             borrow cash (no game-over); rate scales w/ size\n"
            "  repay [amount|all]        pay down loans\n"
            "  fees [off…diabolic]       brokerage difficulty — commission on every trade\n"
            "  step | hour | day         advance 1 min / 1 hour / 1 day\n"
            "  next <ticks>              advance N minutes\n"
            "  run <ticks> [delay]       live auto-advance (delay sec/tick, default 0.05)\n"
            "  save [name] | load [name] persist the world\n"
            "  quit\n"
            "  (1 tick = 1 simulated minute)"
        )

    def _market(self, args) -> str:
        out = [self.header(), ""]
        holds = self.world.portfolio.positions
        if holds:
            out.append(col("  — your holdings —", C.DIM))
            out.append("\n".join(self._row(a) for a in holds))
            out.append("")
        out.append(col("  — crypto board —", C.DIM))
        out.append(self._list_kind(AssetKind.CRYPTO, 99))
        out.append(col("\n  (try: stocks 15 · bonds · find tech · look BTR)", C.DIM))
        return "\n".join(out)

    def _kind_cmd(self, kind: AssetKind, args) -> str:
        n = int(args[0]) if args and args[0].isdigit() else (20 if kind is AssetKind.STOCK else 99)
        return self._list_kind(kind, n)

    def _find(self, args) -> str:
        if not args:
            return "usage: find <text>"
        q = " ".join(args).lower()
        hits = [a for a in self.world.asset_ids()
                if q in self.world.name_of(a).lower() or q in a.split(":", 1)[1].lower()]
        if not hits:
            return f"no matches for {q!r}"
        head = col(f"  {'SYMBOL':<11} {'PRICE':>14}  {'1D':>9}  {'~24h':<16}  NAME", C.DIM)
        return head + "\n" + "\n".join(self._row(a) for a in hits[:25]) + \
            (f"\n  …and {len(hits)-25} more" if len(hits) > 25 else "")

    def _look(self, args) -> str:
        if not args:
            return "usage: look <SYMBOL>"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        t = self.world.market.tick_index
        meta = self.world.meta_of(aid)
        path = [self.engine.price_at(aid, max(0, t - 3 * DAY + i * (3 * DAY // 48))) for i in range(48)]
        lines = [
            col(f"{aid.split(':',1)[1]}  {self.world.name_of(aid)}", C.BOLD),
            f"  price {money(self.world.price(aid))}   "
            f"1h {signed_pct(self.engine.price_at(aid, max(0,t-HOUR)), self.world.price(aid))}   "
            f"1d {signed_pct(self.engine.price_at(aid, max(0,t-DAY)), self.world.price(aid))}",
            f"  3-day path  {col(sparkline(path), C.CYAN)}",
        ]
        kind = self.world.kind_of(aid)
        if kind is AssetKind.STOCK:
            lines.append(f"  sector {meta.sector} · vol {meta.volatility:.0%} · growth {meta.growth_rate:+.0%}")
        elif kind is AssetKind.BOND:
            lines.append(f"  {meta.issuer_type} {meta.rating} · coupon {meta.coupon_rate:.2%} · "
                         f"{meta.maturity_years:.0f}y · default risk {meta.default_prob:.2%}")
        else:
            lines.append(f"  {meta.archetype} · vol {meta.volatility:.0%} · "
                         f"anchor strength {meta.fundamental_strength:.0%}")
        held = self.world.portfolio.positions.get(aid)
        if held:
            lines.append(col(f"  you hold {fmt_qty(held.quantity)} @ avg {money(held.avg_cost)}", C.DIM))
        return "\n".join(lines)

    def _parse_qty(self, aid: str, token: str) -> float | None:
        token = token.lower()
        if token == "all":
            held = self.world.portfolio.positions.get(aid)
            return held.quantity if held else 0.0
        if token.startswith("$"):
            try:
                return float(token[1:]) / self.world.price(aid)
            except ValueError:
                return None
        try:
            return float(token)
        except ValueError:
            return None

    def _buy(self, args) -> str:
        if len(args) < 2:
            return "usage: buy <SYMBOL> <qty|$amount>"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        qty = self._parse_qty(aid, args[1])
        if qty is None or qty <= 0:
            return "invalid quantity"
        res = execute_order(self.world, Order(aid, OrderSide.BUY, qty))
        if res.filled:
            fee_txt = f"  fee {money(res.fee)}" if res.fee else ""
            return col(f"bought {fmt_qty(qty)} {args[0].upper()} @ {money(res.price)} "
                       f"(−{money(-res.cash_delta)}{fee_txt})  cash {money(self.world.portfolio.cash)}", C.GREEN)
        return col(f"order rejected: {res.message}", C.RED)

    def _sell(self, args) -> str:
        if len(args) < 2:
            return "usage: sell <SYMBOL> <qty|all>"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        qty = self._parse_qty(aid, args[1])
        if qty is None or qty <= 0:
            return "invalid quantity"
        res = execute_order(self.world, Order(aid, OrderSide.SELL, qty))
        if res.filled:
            pnl = col(f"{res.realized_pnl:+,.2f}", C.GREEN if res.realized_pnl >= 0 else C.RED)
            return col(f"sold {fmt_qty(qty)} {args[0].upper()} @ {money(res.price)} "
                       f"(+{money(res.cash_delta)}) realized P&L {pnl}  "
                       f"cash {money(self.world.portfolio.cash)}", C.GREEN)
        return col(f"order rejected: {res.message}", C.RED)

    def _port(self, args) -> str:
        w = self.world; pf = w.portfolio; po = w.price_of
        out = [self.header(), ""]
        if not pf.positions:
            out.append("  (no holdings — try 'buy BTR $500' or 'short SLR 50')")
        else:
            out.append(col(f"  {'SYMBOL':<11}{'QTY':>13}{'AVG':>12}{'PRICE':>12}"
                           f"{'VALUE':>13}{'P&L':>18}", C.DIM))
            for aid, pos in pf.positions.items():
                price = w.price(aid)
                val = price * pos.quantity
                pnl = (price - pos.avg_cost) * pos.quantity
                basis = pos.avg_cost * abs(pos.quantity)
                pnlpct = (pnl / basis * 100) if basis else 0
                pnls = col(f"{pnl:+,.2f} ({pnlpct:+.1f}%)", C.GREEN if pnl >= 0 else C.RED)
                tag = col(" SHORT", C.YELLOW) if pos.quantity < 0 else ""
                out.append(f"  {aid.split(':',1)[1]:<11}{fmt_qty(pos.quantity):>13}{money(pos.avg_cost):>12}"
                           f"{money(price):>12}{money(val):>13}{pnls:>26}{tag}")
        hv = pf.holdings_value(po)
        out.append("")
        out.append(f"  cash {money(pf.cash)}   holdings {money(hv)}   equity {money(pf.equity(po))}")
        nwline = f"  net worth {money(pf.net_worth(po))}"
        if pf.loan_balance() > 0:
            nwline += f"   loans {money(pf.loan_balance())} (repay with 'repay all')"
        out.append(nwline)
        out.append(f"  gross exposure {money(pf.gross_exposure(po))}   "
                   f"buying power {money(pf.buying_power(po))}"
                   + (f"   margin debt {money(pf.margin_debt())}" if pf.margin_debt() > 0 else ""))
        out.append(f"  realized P&L {money(pf.realized_pnl)}   "
                   f"unrealized {money(pf.unrealized_pnl(po))}")
        if pf.is_margin_call(po):
            out.append(col("  ⚠ MARGIN CALL — advance time and positions will be liquidated", C.RED))
        return "\n".join(out)

    def _advance(self, ticks: int):
        t0 = self.world.market.tick_index
        self.engine.advance(ticks)
        t1 = self.world.market.tick_index
        self.world.portfolio.accrue_interest(t1 - t0)
        self.world.accrue_coupons(t1 - t0)
        self.world.portfolio.record_net_worth(t1, self.world.price_of)
        events = self.engine.events.fired_between(t0, t1)
        closures = liquidate_for_margin(self.world)
        return events, closures

    def _liquidation_notice(self, closures) -> str:
        if not closures:
            return ""
        lines = [col("  ⚠ MARGIN CALL — forced liquidation:", C.RED)]
        for r in closures:
            sym = r.order.asset_id.split(":", 1)[1]
            lines.append(col(f"     closed {fmt_qty(r.order.quantity)} {sym} @ {money(r.price)} "
                             f"(P&L {r.realized_pnl:+,.2f})", C.RED))
        return "\n" + "\n".join(lines)

    def _next(self, args) -> str:
        ticks = int(args[0]) if args and args[0].lstrip("-").isdigit() else HOUR
        if ticks <= 0:
            return "advance by a positive number of minutes"
        events, closures = self._advance(ticks)
        out = col(f"⏩ advanced {ticks} min → {fmt_clock(self.world.market.tick_index)}", C.DIM)
        return out + self._events_notice(events) + self._liquidation_notice(closures) \
            + "\n" + self.header()

    def _run(self, args) -> str:
        ticks = int(args[0]) if args and args[0].isdigit() else HOUR
        try:
            delay = float(args[1]) if len(args) > 1 else 0.05
        except ValueError:
            return "usage: run <ticks> [delay]  — delay must be a number of seconds"
        live = _color_enabled()
        notices = []
        ev_notices = []
        ran = 0
        try:
            for _ in range(ticks):
                evs, clo = self._advance(1)
                ev_notices += evs
                notices += clo
                ran += 1
                if live:
                    sys.stdout.write("\r" + self.header().splitlines()[1] + "   ")
                    sys.stdout.flush()
                    time.sleep(delay)
        except KeyboardInterrupt:                        # Ctrl-C stops the run, returns to the prompt
            if live:
                sys.stdout.write("\n")
            return col(f"⏹ stopped after {ran}/{ticks} min → "
                       f"{fmt_clock(self.world.market.tick_index)}", C.YELLOW) \
                + self._events_notice(ev_notices[:6]) + self._liquidation_notice(notices)
        if live:
            sys.stdout.write("\n")
        return col(f"⏩ ran {ticks} min → {fmt_clock(self.world.market.tick_index)}", C.DIM) \
            + self._events_notice(ev_notices[:6]) + self._liquidation_notice(notices)

    @staticmethod
    def _parse_horizon(tok: str) -> int:
        tok = tok.lower()
        try:
            if tok.endswith("d"):
                return int(float(tok[:-1]) * DAY)
            if tok.endswith("h"):
                return int(float(tok[:-1]) * HOUR)
            if tok.endswith("m"):
                return int(float(tok[:-1]))
            return int(float(tok))
        except ValueError:
            return -1

    @staticmethod
    def _fmt_horizon(ticks: int) -> str:
        if ticks % DAY == 0:
            return f"{ticks // DAY}d"
        if ticks % HOUR == 0:
            return f"{ticks // HOUR}h"
        return f"{ticks}m"

    def _fees(self, args) -> str:
        from .core.orders import FEE_RATES, FEE_LEVELS
        cfg = self.world.config
        if not args:
            cur = getattr(cfg, "fee_level", "off")
            return (f"brokerage fees: {col(cur, C.BOLD)} ({FEE_RATES.get(cur, 0) * 100:.2f}% per trade)\n"
                    f"  set with 'fees <level>'  —  {' / '.join(FEE_LEVELS)}")
        level = args[0].lower()
        if level not in FEE_RATES:
            return col(f"unknown fee level {level!r} — choose from {', '.join(FEE_LEVELS)}", C.YELLOW)
        cfg.fee_level = level
        return col(f"brokerage fees → {level} ({FEE_RATES[level] * 100:.2f}% per trade)", C.CYAN)

    def _loan(self, args) -> str:
        if not args:
            return "usage: loan <amount>   (interest rate scales with how much you borrow vs net worth)"
        try:
            amt = float(args[0].lstrip("$").replace(",", ""))
        except ValueError:
            return "invalid amount"
        pf = self.world.portfolio
        nw = self.world.net_worth()
        loan = pf.take_loan(amt, nw, self.world.market.tick_index)
        if not loan:
            return col(f"loan rejected — the most you can borrow right now is "
                       f"{money(pf.borrow_limit(nw))}", C.YELLOW)
        return col(f"borrowed {money(amt)} at {loan.apr:.0%} APR.  cash {money(pf.cash)}   "
                   f"loans {money(pf.loan_balance())}", C.GREEN)

    def _repay(self, args) -> str:
        pf = self.world.portfolio
        if pf.loan_balance() <= 0:
            return "you have no outstanding loans"
        if not args or args[0].lower() == "all":
            amt = pf.loan_balance()
        else:
            try:
                amt = float(args[0].lstrip("$").replace(",", ""))
            except ValueError:
                return "invalid amount"
        paid = pf.repay(amt)
        return col(f"repaid {money(paid)}.  cash {money(pf.cash)}   "
                   f"loans {money(pf.loan_balance())}", C.GREEN)

    def _predict(self, args) -> str:
        if not args:
            return "usage: predict <SYMBOL> [horizon, e.g. 1d or 6h]"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        horizon = self._parse_horizon(args[1]) if len(args) > 1 else DAY
        if horizon <= 0:
            return "invalid horizon (try 1d, 6h, 90m)"
        pred = make_prediction(self.world, self.engine, aid, horizon)
        pf = self.world.portfolio
        if pf.cash < pred.cost:
            return col(f"that forecast costs {money(pred.cost)} — you only have {money(pf.cash)}",
                       C.YELLOW)
        pf.cash -= pred.cost
        c = C.GREEN if pred.direction == "UP" else C.RED
        sym = args[0].upper()
        return (col(f"🔮 forecast for {sym}  (paid {money(pred.cost)}, world confidence "
                    f"{pred.confidence:.0%})", C.CYAN)
                + "\n" + f"   now {money(pred.current)}  →  in {self._fmt_horizon(horizon)}: "
                + col(f"~{money(pred.forecast)} ({pred.direction})", c)
                + "\n" + col(f"   likely range {money(pred.low)} – {money(pred.high)}", C.DIM))

    def _events_notice(self, events) -> str:
        if not events:
            return ""
        lines = []
        for ev in events[:6]:
            c = C.GREEN if ev.severity > 0 else C.RED
            tag = "▲" if ev.severity > 0 else "▼"
            big = ev.scope_type in ("market", "class")
            head = col(f"  {tag} {ev.headline}", (C.BOLD + c) if big else c)
            lines.append(head)
        return "\n" + "\n".join(lines)

    def _news(self, args) -> str:
        t = self.world.market.tick_index
        events = self.engine.events.recent(t, lookback_days=14, limit=14)
        if not events:
            return "  (quiet markets — no recent headlines)"
        out = [col("  — recent headlines —", C.DIM)]
        for ev in events:
            c = C.GREEN if ev.severity > 0 else C.RED
            tag = "▲" if ev.severity > 0 else "▼"
            out.append(f"  {col(fmt_clock(ev.fire_tick), C.DIM)}  {col(tag, c)} "
                       f"{col(ev.headline, c if ev.scope_type in ('market','class') else C.RESET)}")
        return "\n".join(out)

    def _short(self, args) -> str:
        if len(args) < 2:
            return "usage: short <SYMBOL> <qty|$amount>"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        qty = self._parse_qty(aid, args[1])
        if qty is None or qty <= 0:
            return "invalid quantity"
        res = execute_order(self.world, Order(aid, OrderSide.SELL, qty))
        if res.filled:
            return col(f"shorted {fmt_qty(qty)} {args[0].upper()} @ {money(res.price)} "
                       f"(+{money(res.cash_delta)})  cash {money(self.world.portfolio.cash)}", C.YELLOW)
        return col(f"order rejected: {res.message}", C.RED)

    def _cover(self, args) -> str:
        if not args:
            return "usage: cover <SYMBOL> [qty|all]"
        aid = self.resolve(args[0])
        if not aid:
            return col(f"unknown symbol {args[0]!r}", C.YELLOW)
        pos = self.world.portfolio.positions.get(aid)
        if not pos or pos.quantity >= 0:
            return f"no short position in {args[0].upper()}"
        if len(args) < 2 or args[1].lower() == "all":
            qty = abs(pos.quantity)
        else:
            qty = self._parse_qty(aid, args[1])
        if qty is None or qty <= 0:
            return "invalid quantity"
        qty = min(qty, abs(pos.quantity))
        res = execute_order(self.world, Order(aid, OrderSide.BUY, qty))
        if res.filled:
            pnl = col(f"{res.realized_pnl:+,.2f}", C.GREEN if res.realized_pnl >= 0 else C.RED)
            return col(f"covered {fmt_qty(qty)} {args[0].upper()} @ {money(res.price)} "
                       f"realized {pnl}  cash {money(self.world.portfolio.cash)}", C.GREEN)
        return col(f"order rejected: {res.message}", C.RED)

    def _save(self, args) -> str:
        name = args[0] if args else "save"
        meta = save_game(self.world, slot_path(name, SAVES_DIR), label=name)
        return col(f"saved → {name}.world   net worth {money(meta['net_worth'])} "
                   f"({meta['return_pct']:+.1f}%)", C.CYAN)

    def _load(self, args) -> str:
        name = args[0] if args else "save"
        path = slot_path(name, SAVES_DIR)
        if not path.exists():
            return col(f"no save named {name}.world", C.YELLOW)
        try:
            self.world = load_game(path, self.universe)
        except Exception as exc:
            return col(f"could not load {name}.world: {exc}", C.RED)
        self.engine = MarketEngine(self.world)
        if not self.world.portfolio.nw_history:
            self.world.portfolio.record_net_worth(self.world.market.tick_index, self.world.price_of)
        return col(f"loaded ← {name}.world", C.CYAN) + "\n" + self.header()

    def _quit(self, args) -> str:
        self.running = False
        return col("see you out there, trader.", C.CYAN)


# --------------------------------------------------------------------------- #
# Interactive loop + world setup
# --------------------------------------------------------------------------- #

def _prompt_new_world(universe) -> World:
    print(col("\n  TRADER PRO — new world\n", C.BOLD + C.CYAN))
    print("  Volatility profiles:")
    for p in (get_profile(n) for n in PROFILE_NAMES):
        print(f"    {p.level} {p.name:<12} {p.tagline}")
    raw = input("\n  profile [4=Normal]: ").strip() or "4"
    try:
        # Guard the range so a stray "0" (or "9", "-1") doesn't index into PROFILE_NAMES[-1]
        # (Apocalyptic) and silently drop the player into the hardest world.
        profile = (PROFILE_NAMES[int(raw) - 1]
                   if raw.isdigit() and 1 <= int(raw) <= len(PROFILE_NAMES) else raw)
        get_profile(profile)
    except (ValueError, IndexError):
        profile = "Normal"
    seed_raw = input("  world seed [20260614]: ").strip()
    seed = int(seed_raw) if seed_raw.lstrip("-").isdigit() else 20260614
    cash_raw = input("  starting cash [5000]: ").strip()
    cash = float(cash_raw) if cash_raw.replace(".", "").isdigit() else 5000.0
    from .core.orders import FEE_LEVELS
    fees_raw = input(f"  brokerage fees [off]  ({' / '.join(FEE_LEVELS)}): ").strip().lower()
    fee_level = fees_raw if fees_raw in FEE_LEVELS else "off"
    return World.new(universe, world_seed=seed, profile=profile, starting_cash=cash, fee_level=fee_level)


def _session_fingerprint(app) -> tuple:
    """A cheap snapshot of the mutable world state — used to tell whether a session actually
    changed anything, so a read-only peek doesn't clobber the shared autosave slot."""
    pf = app.world.portfolio
    return (
        app.world.market.tick_index,
        round(pf.cash, 6),
        round(pf.loan_balance(), 6),
        tuple(sorted((aid, round(p.quantity, 8)) for aid, p in pf.positions.items())),
    )


def repl() -> None:
    # Never let a non-UTF-8 stdout (the default when piped or on a legacy Windows code page)
    # crash on the sparklines / em-dashes / emoji the UI prints.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    setup_logging(install_hooks=False)          # command errors log to logs/trader_pro.log
    universe = load_seed_universe()
    print(col("Welcome to Trader PRO.", C.BOLD + C.CYAN))
    choice = input("  [n]ew world or [l]oad a save? [n]: ").strip().lower()
    if choice.startswith("l"):
        app = TraderApp(universe=universe)
        name = input("  save name [save]: ").strip() or "save"
        print(app.execute(f"load {name}"))
    else:
        app = TraderApp(_prompt_new_world(universe), universe=universe)
    print("\n" + app.execute("market"))
    print(col("\nType 'help' for commands.\n", C.DIM))
    start_fp = _session_fingerprint(app)
    while app.running:
        try:
            line = input(col("trader> ", C.BOLD))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        out = app.execute(line)
        if out:
            print(out)
    # Autosave on the way out so a session is never silently lost — but only if the world
    # actually changed, so a read-only peek (look/market/quit) never clobbers the shared
    # `autosave` slot the TUI and GUI resume from. When it does write, relaunching any
    # front-end resumes right where this game left off.
    if _session_fingerprint(app) != start_fp:
        try:
            save_game(app.world, autosave_path(SAVES_DIR), label="autosave")
            print(col("  · autosaved → autosave.world", C.DIM))
        except Exception as exc:
            log_error(exc, "autosave on quit")


if __name__ == "__main__":
    repl()
