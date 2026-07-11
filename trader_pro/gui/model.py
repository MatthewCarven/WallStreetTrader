"""Pure, Qt-free helpers for the desktop GUI — safe to import and unit-test without PySide6.

Keeping the view logic here (pacing math, the header string, and later the board/chart data)
means the widgets in `app.py` stay thin and everything testable runs under plain pytest. Values
mirror the TUI's so the GUI paces and reads identically.
"""
from __future__ import annotations

from ..cli import TraderApp, fmt_clock, money
from ..core import World, load_seed_universe
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
