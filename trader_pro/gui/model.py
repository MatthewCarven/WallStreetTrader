"""Pure, Qt-free helpers for the desktop GUI — safe to import and unit-test without PySide6.

Keeping the view logic here (pacing math, the header string, and later the board/chart data)
means the widgets in `app.py` stay thin and everything testable runs under plain pytest. Values
mirror the TUI's so the GUI paces and reads identically.
"""
from __future__ import annotations

from collections import namedtuple

from ..cli import TraderApp, fmt_clock, money, fmt_qty
from ..core import AssetKind, World, load_seed_universe
from ..core.engine import DAY, HOUR, WEEK
from ..core.orders import fee_rate
from ..core.portfolio import MAINTENANCE_MARGIN_RATIO
from ..persistence import autosave_path, has_autosave, load_game

# Live-play speeds as ticks (sim-minutes) advanced per REAL second — mirrors tui.py SPEEDS.
# Index 0 is a calm 1 sim-minute per real second.
SPEEDS = [("1 min/s", 1), ("10 min/s", 10), ("1 hr/s", 60), ("10 hr/s", 600)]
TIMER_MS = 250              # QTimer cadence; pacing is frame-rate independent (see steps_for)
AUTOSAVE_SECS = 30         # wall-clock throttle for periodic autosave while playing
DEFAULT_SEED = 20260614    # the same fresh-world seed the CLI and TUI use

# Price-chart ranges (label, span in ticks), cycled with the `c` key — mirrors tui.py CHART_RANGES.
CHART_RANGES = [("1H", HOUR), ("1D", DAY), ("3D", 3 * DAY), ("1W", WEEK)]

# Retro green-phosphor palette (echoes the TUI's colour scheme).
BG = "#07120b"
PANEL = "#0d1f14"
FG = "#b8f0c0"
# Fixed P&L semantics: profit / up is green, loss / down is red — kept independent of the theme
# accent below, so even a blue or red theme still shows gains in green and losses in red (the
# universal trading convention). Change the *accent*, not these, to reskin the app.
GREEN = "#2fae4e"
GREEN_HI = "#38c172"
RED = "#e5484d"
AMBER = "#ffb000"
DIM = "#7c8a80"


def _scale_hex(hex_color: str, factor: float) -> str:
    """Multiply a ``#rrggbb`` colour's channels by ``factor`` (clamped to 0–255): >1 brightens,
    <1 dims. Used to derive the accent's highlight and row-selection shades from one picked colour."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (max(0, min(255, round(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def accent_palette(accent: str | None) -> tuple[str, str, str]:
    """Resolve ``(ACCENT, ACCENT_HI, SELECTION)`` for the theme.

    ``None`` keeps the hand-tuned phosphor-green defaults. A custom accent derives a brighter
    highlight (×1.2) and a dimmed board row-selection (×0.6 — which reproduces the original
    ``#1c682f`` exactly for the default green, so nothing shifts unless you actually pick a colour).
    """
    if not accent:
        return "#2fae4e", "#38c172", "#1c682f"
    return accent, _scale_hex(accent, 1.2), _scale_hex(accent, 0.6)


def _saved_accent() -> str | None:
    """The user's saved accent colour, or None. Defensive: never raises at import time."""
    try:
        from .settings import accent_color
        return accent_color()
    except Exception:
        return None


class Theme:
    """The accent-derived chrome colours, in one **mutable** object.

    These were three module-level constants resolved at import time, which is precisely why the
    accent picker could only say "restart to apply": every stylesheet string in ``app.py`` baked
    the value in when its widget was built, so rebinding a module attribute afterwards changed
    nothing. Reading ``THEME.accent`` at *format* time is what makes a live repaint possible —
    the picker mutates this object and asks the window to restyle (``TraderGUI._restyle_theme``).

    Only **chrome** lives here (borders, menu highlights, the banner, row selection).
    ``GREEN`` / ``GREEN_HI`` / ``RED`` are P&L *semantics* — profit green, loss red, in every
    theme — and stay module constants on purpose.
    """

    __slots__ = ("accent", "accent_hi", "selection")

    def __init__(self, accent: str | None = None) -> None:
        self.set(accent)

    def set(self, accent: str | None) -> None:
        """Point the theme at a new accent. ``None`` restores the default phosphor green."""
        self.accent, self.accent_hi, self.selection = accent_palette(accent)

    def as_tuple(self) -> tuple[str, str, str]:
        """``(accent, accent_hi, selection)`` — handy for tests and for snapshotting."""
        return self.accent, self.accent_hi, self.selection

    def __repr__(self) -> str:                     # pragma: no cover — debugging aid
        return f"Theme(accent={self.accent!r}, accent_hi={self.accent_hi!r}, selection={self.selection!r})"


# The live theme. Seeded from the saved accent at import; mutated in place by the Appearance
# menu. There are deliberately no ACCENT / ACCENT_HI / SELECTION module constants any more —
# a stale copy of these values is the bug this object exists to prevent.
THEME = Theme(_saved_accent())


def steps_for(elapsed: float, ticks_per_sec: float, accum: float) -> tuple[int, float]:
    """Whole sim-minutes to advance for `elapsed` real seconds at `ticks_per_sec`, carrying the
    fractional remainder forward in `accum`. A single step is capped (elapsed clamped to 1.0s) so
    a stall — GC pause, sleep, a modal held open — can't fast-forward the market. Pure; this is
    the frame-rate-independent core of the play loop, unit-tested without Qt. Mirrors tui.py:673.
    """
    accum += min(elapsed, 1.0) * ticks_per_sec
    steps = int(accum)
    return steps, accum - steps


def boot() -> tuple[TraderApp, bool]:
    """Resume the last autosave or start a fresh world — mirrors run_tui() (tui.py:1417).
    Returns (trader, resumed)."""
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
        world = World.new(universe, world_seed=DEFAULT_SEED, profile="Normal",
                          starting_cash=5000.0, fee_level="off")
    return TraderApp(world, universe=universe), resumed


def _span(text: str, color: str, *, bold: bool = False) -> str:
    weight = "font-weight:bold;" if bold else ""
    return f'<span style="{weight}color:{color}">{text}</span>'


def header_html(world: World) -> str:
    """The dashboard header as Qt rich text for a QLabel — the same content as
    TraderApp.header() (cli.py:110), formatted with HTML colour spans instead of ANSI codes."""
    w = world
    pf = w.portfolio
    po = w.price_of
    eq = w.equity()
    nw = pf.net_worth(po)
    ret = (eq / w.config.starting_cash - 1) * 100
    nwret = (nw / w.config.starting_cash - 1) * 100
    sp = "&nbsp;&nbsp;&nbsp;"

    line1 = (
        _span("TRADER PRO", THEME.accent_hi, bold=True) + "&nbsp;&nbsp;"
        + _span(f"seed {w.config.world_seed} · {w.config.profile} · "
                f"{fmt_clock(w.market.tick_index)}", DIM)
    )
    line2 = (
        f"cash {money(pf.cash)}{sp}equity {money(eq)}{sp}"
        f"return {_span(f'{ret:+.1f}%', GREEN if ret >= 0 else RED)}{sp}"
        f"sentiment {w.market.sentiment:+.2f}{sp}"
        f"rate {w.market.interest_rate * 100:.2f}%"
    )
    line3 = (
        f"net worth {_span(money(nw), FG, bold=True)} "
        f"({_span(f'{nwret:+.1f}%', GREEN if nwret >= 0 else RED)}){sp}"
        f"buying power {money(pf.buying_power(po))}"
    )
    if pf.loan_balance() > 0:
        line3 += f"{sp}loans {money(pf.loan_balance())}"
    if pf.margin_debt() > 0:
        line3 += f"{sp}margin debt {money(pf.margin_debt())}"
    if pf.is_margin_call(po):
        line3 += _span(f"{sp}⚠ MARGIN CALL", RED, bold=True)
    return f"{line1}<br>{line2}<br>{line3}"


# --------------------------------------------------------------------------- #
# Market board — the data behind the table, ported from the TUI's _RowCtx /
# BOARD_COLUMNS / _chgNd / _add_row (tui.py:509-533, 715, 878). Pure: the Qt
# model in app.py maps these onto display / colour / alignment roles.
# --------------------------------------------------------------------------- #

NOTABLE_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "GOOGL", "TSLA"]

# One board row's precomputed values. `qty` is signed (negative = short); `value` = qty * price.
RowCtx = namedtuple("RowCtx", "sym price chg chg7d chg31d qty value cost pnl")

# One rendered cell: display text, colour, right-alignment, bold. Qt-free on purpose.
Cell = namedtuple("Cell", "text color right bold")

BOARD_COLUMNS = [
    ("symbol", "Symbol"),
    ("price", "Price"),
    ("chg", "1D %"),
    ("chg7d", "7D %"),
    ("chg31d", "31D %"),
    ("pos", "Pos"),
    ("value", "Value"),
    ("cost", "Cost/Sh"),
    ("pnl", "P&L %"),
]


def chg_pct(world, engine, aid: str, num_days: int) -> float:
    """N-day % change — price now vs `num_days` ago. Mirrors the TUI's _chgNd (tui.py:715).

    Always a number: on a world younger than the window the lookback clamps to tick 0, giving
    "change since the world opened". That is the right value to *order* by (movers, sort-by-%,
    the ticker arrow), so every sorter calls this. Display columns use :func:`chg_col`."""
    t = world.market.tick_index
    price = world.price(aid)
    prev = engine.price_at(aid, max(0, t - num_days * DAY))
    return (price / prev - 1) * 100 if prev > 0 else 0.0


def has_window(world, num_days: int) -> bool:
    """True once the world is old enough for an honest `num_days`-day lookback."""
    return world.market.tick_index >= num_days * DAY


def chg_col(world, engine, aid: str, num_days: int) -> float | None:
    """The *display* value for a change column: ``None`` until a full window exists.

    Without this, a 31-minute-old world shows the identical number in 1D / 7D / 31D — correct
    (they all clamp to tick 0) but indistinguishable from a broken column."""
    return chg_pct(world, engine, aid, num_days) if has_window(world, num_days) else None


def row_ctx(world, engine, aid: str) -> RowCtx:
    """Precompute one board row for `aid`. Mirrors the TUI's _add_row (tui.py:878)."""
    pos = world.portfolio.positions.get(aid)
    price = world.price(aid)
    qty = pos.quantity if pos else 0.0
    cost = pos.avg_cost if pos else 0.0
    # Unrealized return if closed now: +% in profit for longs and shorts alike (a short profits as
    # price falls). Fees ignored, matching the side panel's P&L.
    pnl = (price - cost) / cost * 100 * (1.0 if qty >= 0 else -1.0) if (qty and cost) else 0.0
    return RowCtx(
        aid.split(":", 1)[1], price,
        chg_col(world, engine, aid, 1),
        chg_col(world, engine, aid, 7),
        chg_col(world, engine, aid, 31),
        qty, qty * price, cost, pnl,
    )


def _pct_cell(v: float | None) -> Cell:
    """One change-column cell. ``None`` (see :func:`chg_col`) renders as a dim em dash — the
    world isn't old enough for that lookback yet. Mirrors the TUI's _pct_cell."""
    if v is None:
        return Cell("—", DIM, True, False)
    return Cell(f"{v:+.2f}%", GREEN if v >= 0 else RED, True, False)


def cell(ctx: RowCtx, col_id: str) -> Cell:
    """Render one board cell (text, colour, alignment, weight) — the Qt-free equivalent of the
    BOARD_COLUMNS render lambdas (tui.py:511)."""
    if col_id == "symbol":
        return Cell(ctx.sym, FG, False, True)
    if col_id == "price":
        return Cell(money(ctx.price), FG, True, False)
    if col_id == "chg":
        return _pct_cell(ctx.chg)
    if col_id == "chg7d":
        return _pct_cell(ctx.chg7d)
    if col_id == "chg31d":
        return _pct_cell(ctx.chg31d)
    if col_id == "pos":
        color = AMBER if ctx.qty < 0 else (FG if ctx.qty else DIM)
        return Cell(fmt_qty(ctx.qty) if ctx.qty else "·", color, True, False)
    if col_id == "value":
        color = GREEN if ctx.value > 0 else (RED if ctx.value < 0 else DIM)
        return Cell(money(ctx.value) if ctx.value else "·", color, True, False)
    if col_id == "cost":
        return Cell(money(ctx.cost) if ctx.cost else "·", DIM, True, False)
    if col_id == "pnl":
        color = GREEN if ctx.pnl > 0 else (RED if ctx.pnl < 0 else DIM)
        return Cell(f"{ctx.pnl:+.2f}%" if (ctx.qty and ctx.cost) else "·", color, True, False)
    raise KeyError(col_id)


def default_watchlist(world) -> list[str]:
    """The starting watchlist: every crypto coin plus a few notable stocks. Mirrors tui.py:613."""
    watch = [f"CRYPTO:{c.symbol}" for c in world.universe.crypto]
    for sym in NOTABLE_STOCKS:
        aid = f"STOCK:{sym}"
        if world.has_asset(aid):
            watch.append(aid)
    return watch


def board_ids(world) -> list[str]:
    """The default board: held positions pinned on top, then the watchlist, deduped. Equivalent to
    `visible_ids(view_source=None, owned_only=False, sort_by_change=False)`."""
    held = [a for a in world.portfolio.positions if world.has_asset(a)]
    seen, out = set(), []
    for aid in held + default_watchlist(world):
        if aid not in seen and world.has_asset(aid):
            seen.add(aid)
            out.append(aid)
    return out


def kind_ids(world, kind: AssetKind) -> list[str]:
    """All asset ids of a given kind (STOCK / CRYPTO / BOND). Mirrors the TUI's _kind_ids."""
    return [a for a in world.asset_ids() if world.kind_of(a) is kind]


def visible_ids(world, engine, *, view_source, owned_only, sort_by_change, watch,
                view_page, page_size) -> tuple[list[str], str | None]:
    """Which asset ids the board should show, plus an optional 'next page' label. A faithful port
    of the TUI's _visible() (tui.py:763): held positions of the current view pin to the top, then
    one page of `page_size` unheld candidates. `sort_by_change` orders candidates by 1D % desc.
    `view_source` None means the default holdings+watchlist view (no paging)."""
    pf = world.portfolio
    held = [a for a in pf.positions if world.has_asset(a)]
    by_change = lambda aid: chg_pct(world, engine, aid, 1)

    if owned_only:
        return (sorted(held, key=by_change, reverse=True) if sort_by_change else held), None

    if view_source is None:
        seen, out = set(), []
        for aid in held + watch:
            if aid not in seen and world.has_asset(aid):
                seen.add(aid)
                out.append(aid)
        if sort_by_change:
            out = sorted(out, key=by_change, reverse=True)
        return out, None

    src = set(view_source)
    held = [a for a in held if a in src]
    owned = set(held)
    cands = [a for a in view_source if a not in owned and world.has_asset(a)]
    if sort_by_change:
        cands = sorted(cands, key=by_change, reverse=True)
    if not cands:
        return held, None
    total = (len(cands) + page_size - 1) // page_size
    page = view_page % total
    page_ids = cands[page * page_size:(page + 1) * page_size]
    label = f"page {page + 1}/{total}" if total > 1 else None
    return held + page_ids, label


def asset_detail_html(world, aid: str) -> str:
    """Fundamentals for the highlighted asset, as Qt rich text. Reads `world.meta_of(aid)` (the
    seed record); fields differ by kind (models.py: StockSeed / BondSeed / CryptoSeed)."""
    kind = world.kind_of(aid)
    meta = world.meta_of(aid)
    sym = aid.split(":", 1)[1]
    head = (f'{_span(sym, FG, bold=True)}  {_span(world.name_of(aid), DIM)}<br>'
            f'{_span(kind.name.title(), AMBER)}')
    if kind is AssetKind.STOCK:
        rows = [
            ("sector", meta.sector),
            ("industry", meta.sub_industry),
            ("fair value", money(meta.fair_value)),
            ("growth", f"{meta.growth_rate * 100:.1f}%/yr"),
            ("volatility", f"{meta.volatility * 100:.0f}%"),
            ("market cap", f"${meta.market_cap / 1e9:.1f}B"),
        ]
    elif kind is AssetKind.BOND:
        rows = [
            ("issuer", meta.issuer_type),
            ("rating", meta.rating),
            ("coupon", f"{meta.coupon_rate * 100:.2f}%"),
            ("maturity", f"{meta.maturity_years:g}y"),
            ("base yield", f"{meta.base_yield * 100:.2f}%"),
        ]
    else:  # CRYPTO
        rows = [
            ("archetype", meta.archetype),
            ("fair value", money(meta.fair_value)),
            ("volatility", f"{meta.volatility * 100:.0f}%"),
            ("anchor", f"{meta.fundamental_strength:.2f}"),
            ("supply", f"{meta.circulating_supply:,.0f}"),
        ]
    body = "<br>".join(f'{_span(k + ":", DIM)} {v}' for k, v in rows)
    return f"{head}<br>{body}"


def trade_quantity(world, aid: str, verb: str, token: str) -> float:
    """Resolve an order quantity from the raw input, the pure core of the TUI's TradeDialog._act
    (tui.py:242). Empty => max (buying power / whole position); 'all' => the whole long/short;
    '$amount' => amount / price; else a plain float. Returns 0.0 if the token is unparseable."""
    pf = world.portfolio
    price = world.price(aid)
    pos = pf.positions.get(aid)
    token = token.strip()
    if not token:
        if verb == "buy":
            # blank 'buy' spends cash on hand only — no 2:1 margin. Divide by (price + commission)
            # so a max buy never tips into margin even with fees on. Explicit qty / $amount can
            # still use margin (execute_order enforces the initial-margin limit).
            per_share = price * (1 + fee_rate(getattr(world.config, "fee_level", "off")))
            return max(0.0, pf.cash) / per_share if per_share > 0 else 0.0
        if verb == "short":
            return pf.buying_power(world.price_of) / price if price else 0.0
        if verb == "sell":
            return pos.quantity if pos and pos.quantity > 0 else 0.0
        if verb == "cover":
            return -pos.quantity if pos and pos.quantity < 0 else 0.0
        return 0.0
    low = token.lower()
    if verb == "sell" and low == "all":
        return pos.quantity if pos and pos.quantity > 0 else 0.0
    if verb == "cover" and low == "all":
        return -pos.quantity if pos and pos.quantity < 0 else 0.0
    tok = low.replace(",", "")
    try:
        return float(tok[1:]) / price if tok.startswith("$") else float(tok)
    except ValueError:
        return 0.0


def margin_fill(world) -> float:
    """Margin-risk meter level in [0,1] = MAINTENANCE_MARGIN_RATIO * gross_exposure / equity,
    clamped. 0 = all cash (safe); ~0.5 = buying power exhausted (gross = 2x equity); 1 = the
    margin-call line (gross = 4x equity, maintenance_excess <= 0)."""
    pf = world.portfolio
    po = world.price_of
    equity = pf.equity(po)
    if equity <= 0:
        return 1.0
    return max(0.0, min(1.0, MAINTENANCE_MARGIN_RATIO * pf.gross_exposure(po) / equity))


def margin_color(fill: float) -> tuple:
    """Meter colour by fill: blue (safe/empty) -> amber (~half, buying power gone) -> red (full,
    margin call). Returns an (r, g, b) tuple."""
    fill = max(0.0, min(1.0, fill))
    blue, amber, red = (59, 130, 246), (255, 176, 0), (229, 72, 77)
    if fill <= 0.5:
        a, b, t = blue, amber, fill / 0.5
    else:
        a, b, t = amber, red, (fill - 0.5) / 0.5
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def margin_call_message(closures) -> str:
    """Readable summary of forced margin liquidations (liquidate_for_margin results) for the popup."""
    lines = [f"• force-sold {fmt_qty(c.order.quantity)} {c.order.asset_id.split(':', 1)[1]} "
             f"@ {money(c.price)}   (P&L {c.realized_pnl:+,.2f})" for c in closures]
    return ("The market moved against your leverage. To restore your maintenance margin the broker "
            "liquidated:\n\n" + "\n".join(lines))


POSITION_COLUMNS = [("sym", "Symbol"), ("qty", "Qty"), ("cost", "Avg Cost"),
                    ("value", "Value"), ("pnl", "P&L"), ("pnlpct", "P&L %")]


def position_rows(world) -> list:
    """One row per held position: (aid, sym, qty, avg_cost, value, unrealized_pnl, pnl_pct).
    qty is signed (negative = short); pnl / pnl_pct are the unrealized close-now result (a short
    profits as price falls)."""
    w = world
    pf = w.portfolio
    rows = []
    for aid in pf.positions:
        if not w.has_asset(aid):
            continue
        pos = pf.positions[aid]
        price = w.price(aid)
        qty = pos.quantity
        pnl = (price - pos.avg_cost) * qty
        pnlpct = ((price / pos.avg_cost - 1) * 100 * (1.0 if qty >= 0 else -1.0)
                  if pos.avg_cost else 0.0)
        rows.append((aid, aid.split(":", 1)[1], qty, pos.avg_cost, qty * price, pnl, pnlpct))
    return rows


def movers_ids(world, engine, n: int = 12) -> list:
    """Top-n 1D% gainers then top-n losers across the whole market, deduped — the 'movers' board
    view. Mirrors the TUI's _movers (tui.py:727)."""
    rows = sorted(((chg_pct(world, engine, aid, 1), aid) for aid in world.asset_ids()),
                  reverse=True)
    ordered = [aid for _, aid in rows[:n]] + [aid for _, aid in reversed(rows[-n:])]
    seen, out = set(), []
    for aid in ordered:
        if aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def ticker_text(world, engine, watch) -> str:
    """The scrolling ticker-tape string: watchlist symbol · price · 1D% arrow. Mirrors _build_ticker."""
    segs = []
    for aid in watch[:18]:
        if not world.has_asset(aid):
            continue
        chg = chg_pct(world, engine, aid, 1)
        # money() (not `:,.2f`) so sub-cent coins keep ~4 significant figures — see tui._build_ticker.
        segs.append(f"{aid.split(':', 1)[1]} {money(world.price(aid))} "
                    f"{'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%")
    return "        ".join(segs) + "        " if segs else ""


def event_entry(event) -> tuple:
    """(text, colour) for one market event in the news feed. Green if it pushed prices up."""
    up = event.severity >= 0
    return (f"{fmt_clock(event.fire_tick)}  {'▲' if up else '▼'} {event.headline}",
            GREEN if up else RED)


def closure_entry(closure) -> tuple:
    """(text, colour) for a forced margin liquidation in the news feed."""
    c = closure
    return (f"⚠ MARGIN CALL — closed {fmt_qty(c.order.quantity)} {c.order.asset_id.split(':', 1)[1]} "
            f"@ {money(c.price)} (P&L {c.realized_pnl:+,.2f})", RED)


def fill_entry(verb: str, qty: float, sym: str, res) -> tuple:
    """(text, colour) for one executed trade fill in the activity log — the buy/sell sibling of
    event_entry / closure_entry. Colour matches the TradeDialog verb buttons (buy/cover green,
    sell red, short amber). `res` is an order result carrying .price/.fee/.realized_pnl."""
    extra = ""
    if res.fee:
        extra += f"   fee {money(res.fee)}"
    if res.realized_pnl:
        extra += f"   realized {money(res.realized_pnl)}"
    color = {"buy": GREEN, "sell": RED, "short": AMBER, "cover": GREEN_HI}.get(verb, FG)
    return (f"{verb.upper()} {fmt_qty(qty)} {sym} @ {money(res.price)}{extra}", color)


def pending_fill_entry(res) -> tuple:
    """(text, colour) for a resting stop/limit order that fired — a fill (green) or, when it can't
    clear margin at trigger time, a cancellation (amber). `res.message` already reads
    'limit filled' / 'stop cancelled: …' from orders.process_pending."""
    sym = res.order.asset_id.split(":", 1)[1]
    if res.filled:
        return (f"◆ {res.message} — {res.order.side.value} {fmt_qty(res.order.quantity)} "
                f"{sym} @ {money(res.price)}", GREEN)
    return (f"◇ {res.message} ({sym})", AMBER)


def save_info_line(info) -> str:
    """One-line summary of a save slot (persistence.SaveInfo) for the load browser."""
    tag = "  (autosave)" if info.is_autosave else ""
    if info.corrupt:
        return f"{info.name}{tag}   — corrupt / unreadable"
    return (f"{info.name}{tag}   net worth {money(info.net_worth)} ({info.return_pct:+.1f}%)   "
            f"· {info.profile} · {info.saved_at}")


def prediction_summary(pred) -> str:
    """Readable forecast line for a bought Prediction (predictions.make_prediction)."""
    return (f"FORECAST {pred.asset_id.split(':', 1)[1]}: {pred.direction} to ~{money(pred.forecast)} "
            f"(range {money(pred.low)}–{money(pred.high)}), confidence {pred.confidence * 100:.0f}%")
