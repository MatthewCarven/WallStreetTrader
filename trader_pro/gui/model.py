"""Pure, Qt-free helpers for the desktop GUI — safe to import and unit-test without PySide6.

Keeping the view logic here (pacing math, the header string, and later the board/chart data)
means the widgets in `app.py` stay thin and everything testable runs under plain pytest. Values
mirror the TUI's so the GUI paces and reads identically.
"""
from __future__ import annotations

from collections import namedtuple

from ..cli import TraderApp, fmt_clock, money
from ..core import AssetKind, World, load_seed_universe
from ..core.engine import DAY
from ..persistence import autosave_path, has_autosave, load_game

# Live-play speeds as ticks (sim-minutes) advanced per REAL second — mirrors tui.py SPEEDS.
# Index 0 is a calm 1 sim-minute per real second.
SPEEDS = [("1 min/s", 1), ("10 min/s", 10), ("1 hr/s", 60), ("10 hr/s", 600)]
TIMER_MS = 250              # QTimer cadence; pacing is frame-rate independent (see steps_for)
AUTOSAVE_SECS = 30         # wall-clock throttle for periodic autosave while playing
DEFAULT_SEED = 20260614    # the same fresh-world seed the CLI and TUI use

# Retro green-phosphor palette (echoes the TUI's colour scheme).
BG = "#07120b"
PANEL = "#0d1f14"
FG = "#b8f0c0"
GREEN = "#2fae4e"
GREEN_HI = "#38c172"
RED = "#e5484d"
AMBER = "#ffb000"
DIM = "#7c8a80"


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
        _span("TRADER PRO", GREEN_HI, bold=True) + "&nbsp;&nbsp;"
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
    """N-day % change — price now vs `num_days` ago. Mirrors the TUI's _chgNd (tui.py:715)."""
    t = world.market.tick_index
    price = world.price(aid)
    prev = engine.price_at(aid, max(0, t - num_days * DAY))
    return (price / prev - 1) * 100 if prev > 0 else 0.0


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
        chg_pct(world, engine, aid, 1),
        chg_pct(world, engine, aid, 7),
        chg_pct(world, engine, aid, 31),
        qty, qty * price, cost, pnl,
    )


def cell(ctx: RowCtx, col_id: str) -> Cell:
    """Render one board cell (text, colour, alignment, weight) — the Qt-free equivalent of the
    BOARD_COLUMNS render lambdas (tui.py:511)."""
    if col_id == "symbol":
        return Cell(ctx.sym, FG, False, True)
    if col_id == "price":
        return Cell(money(ctx.price), FG, True, False)
    if col_id == "chg":
        return Cell(f"{ctx.chg:+.2f}%", GREEN if ctx.chg >= 0 else RED, True, False)
    if col_id == "chg7d":
        return Cell(f"{ctx.chg7d:+.2f}%", GREEN if ctx.chg7d >= 0 else RED, True, False)
    if col_id == "chg31d":
        return Cell(f"{ctx.chg31d:+.2f}%", GREEN if ctx.chg31d >= 0 else RED, True, False)
    if col_id == "pos":
        color = AMBER if ctx.qty < 0 else (FG if ctx.qty else DIM)
        return Cell(f"{ctx.qty:g}" if ctx.qty else "·", color, True, False)
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
