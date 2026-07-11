"""Pure unit tests for the GUI's Qt-free helpers (no PySide6 needed)."""
from trader_pro.cli import TraderApp
from trader_pro.core import World, load_seed_universe
from trader_pro.gui.model import (
    AMBER, DIM, GREEN, RED, RowCtx, board_ids, boot, cell, header_html, row_ctx, steps_for,
)


def test_steps_for_accumulates_fractional():
    s, acc = steps_for(0.3, 1, 0.0)
    assert s == 0 and abs(acc - 0.3) < 1e-9
    s, acc = steps_for(0.3, 1, acc)            # 0.6 banked
    assert s == 0
    s, acc = steps_for(0.5, 1, acc)            # crosses 1.0 -> one whole minute
    assert s == 1 and abs(acc - 0.1) < 1e-9


def test_steps_for_caps_a_single_stall():
    # a long stall at 1 tick/s still advances only one minute (elapsed clamped to 1.0s)
    s, _ = steps_for(100.0, 1, 0.0)
    assert s == 1


def test_steps_for_fast_speed():
    s, acc = steps_for(1.0, 60, 0.0)           # 1 hr/s
    assert s == 60 and abs(acc) < 1e-9


def test_header_html_has_key_fields():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    html = header_html(world)
    for token in ("TRADER PRO", "net worth", "buying power", "Normal", "sentiment"):
        assert token in html


def test_boot_returns_a_trader():
    trader, resumed = boot()
    assert trader.world is not None
    assert isinstance(resumed, bool)


def test_board_ids_and_row_ctx_fresh_world():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    ids = board_ids(world)
    assert ids, "the default board should list the watchlist"
    assert all(":" in aid for aid in ids)                    # ids are KIND:CODE
    ctx = row_ctx(world, trader.engine, ids[0])
    assert ":" not in ctx.sym                                 # symbol stripped of its KIND: prefix
    assert ctx.price > 0
    assert ctx.qty == 0.0 and ctx.cost == 0.0 and ctx.pnl == 0.0   # nothing held on a fresh world


def test_cell_formatting_and_colours():
    up = RowCtx("BTR", 100.0, 2.5, 1.0, 3.0, 0.0, 0.0, 0.0, 0.0)
    c = cell(up, "chg")
    assert c.text == "+2.50%" and c.color == GREEN and c.right and not c.bold
    assert cell(up._replace(chg=-1.25), "chg").color == RED
    # a flat position shows a dim placeholder in Pos / Value
    assert cell(up, "pos").text == "·" and cell(up, "pos").color == DIM
    assert cell(up, "value").text == "·"
    # the symbol cell is bold and left-aligned
    sym = cell(up, "symbol")
    assert sym.text == "BTR" and sym.bold and not sym.right


def test_cell_short_position_colours():
    # a short: negative qty (amber Pos), negative value (red), profit green when price below cost
    short = RowCtx("SLR", 90.0, -1.0, 0.0, 0.0, -5.0, -450.0, 100.0, 10.0)
    assert cell(short, "pos").color == AMBER
    assert cell(short, "value").color == RED
    assert cell(short, "pnl").text == "+10.00%" and cell(short, "pnl").color == GREEN
