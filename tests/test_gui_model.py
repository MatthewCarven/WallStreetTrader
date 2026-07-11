"""Pure unit tests for the GUI's Qt-free helpers (no PySide6 needed)."""
from trader_pro.cli import TraderApp
from trader_pro.core import AssetKind, World, load_seed_universe
from trader_pro.gui.model import (
    AMBER, DIM, GREEN, RED, RowCtx, asset_detail_html, board_ids, boot, cell, chg_pct,
    default_watchlist, header_html, kind_ids, row_ctx, steps_for, trade_quantity, visible_ids,
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


def test_kind_ids_filters_by_kind():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    crypto = kind_ids(world, AssetKind.CRYPTO)
    assert crypto and all(world.kind_of(a) is AssetKind.CRYPTO for a in crypto)
    assert len(kind_ids(world, AssetKind.STOCK)) > 25          # big enough to page


def test_visible_ids_views_and_paging():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    eng = TraderApp(world, universe=uni).engine
    watch = default_watchlist(world)

    # watchlist view (source None): the deduped watch, no page label, nothing held
    ids, label = visible_ids(world, eng, view_source=None, owned_only=False,
                             sort_by_change=False, watch=watch, view_page=0, page_size=25)
    assert ids == watch and label is None

    # owned view: empty on a fresh world
    ids, label = visible_ids(world, eng, view_source=None, owned_only=True,
                             sort_by_change=False, watch=watch, view_page=0, page_size=25)
    assert ids == [] and label is None

    # stocks view: a page of 25 with a page label; page 1 differs from page 0
    stocks = kind_ids(world, AssetKind.STOCK)
    ids0, label0 = visible_ids(world, eng, view_source=stocks, owned_only=False,
                               sort_by_change=False, watch=watch, view_page=0, page_size=25)
    ids1, _ = visible_ids(world, eng, view_source=stocks, owned_only=False,
                          sort_by_change=False, watch=watch, view_page=1, page_size=25)
    assert len(ids0) == 25 and label0 is not None
    assert ids1 != ids0


def test_visible_ids_sort_orders_by_change_desc():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    eng = trader.engine
    trader._advance(3 * 1440)                                   # a few days so 1D % varies
    watch = default_watchlist(world)
    stocks = kind_ids(world, AssetKind.STOCK)
    ids, _ = visible_ids(world, eng, view_source=stocks, owned_only=False,
                         sort_by_change=True, watch=watch, view_page=0, page_size=25)
    chgs = [chg_pct(world, eng, a, 1) for a in ids]
    assert chgs == sorted(chgs, reverse=True)


def test_chart_ranges_defined():
    from trader_pro.gui.model import CHART_RANGES
    assert [label for label, _ in CHART_RANGES] == ["1H", "1D", "3D", "1W"]
    assert all(span > 0 for _, span in CHART_RANGES)


def test_asset_detail_html_by_kind():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    for kind, field in ((AssetKind.STOCK, "sector"), (AssetKind.BOND, "rating"),
                        (AssetKind.CRYPTO, "archetype")):
        aid = kind_ids(world, kind)[0]
        html = asset_detail_html(world, aid)
        assert aid.split(":", 1)[1] in html         # symbol shown
        assert kind.name.title() in html            # kind shown
        assert field in html                        # kind-specific fundamental label present


def test_trade_quantity_parsing():
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    aid = kind_ids(world, AssetKind.CRYPTO)[0]
    price = world.price(aid)
    assert trade_quantity(world, aid, "buy", "10") == 10                      # plain number
    assert abs(trade_quantity(world, aid, "buy", "$1000") - 1000 / price) < 1e-9   # dollar amount
    bp = world.portfolio.buying_power(world.price_of)
    assert abs(trade_quantity(world, aid, "buy", "") - bp / price) < 1e-6     # empty buy => max
    assert trade_quantity(world, aid, "sell", "") == 0.0                      # nothing held
    assert trade_quantity(world, aid, "sell", "all") == 0.0
    assert trade_quantity(world, aid, "buy", "abc") == 0.0                    # garbage => 0


def test_margin_fill_and_color():
    from trader_pro.gui.model import margin_fill, margin_color
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    assert margin_fill(world) == 0.0                       # all cash, nothing held => empty
    assert margin_color(0.0)[2] > margin_color(0.0)[0]     # bluer than red at empty
    assert margin_color(1.0)[0] > margin_color(1.0)[2]     # redder than blue at full


def test_margin_call_message():
    from trader_pro.core import ExecutionResult, Order, OrderSide
    from trader_pro.gui.model import margin_call_message
    res = ExecutionResult(True, Order("CRYPTO:BTR", OrderSide.SELL, 0.5),
                          price=60000.0, realized_pnl=-1234.0, message="margin liquidation")
    msg = margin_call_message([res])
    assert "BTR" in msg and "0.5" in msg and "liquidat" in msg.lower()


def test_position_rows_after_buy():
    from trader_pro.core import Order, OrderSide, execute_order
    from trader_pro.gui.model import position_rows
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    aid = kind_ids(world, AssetKind.CRYPTO)[0]
    qty = trade_quantity(world, aid, "buy", "$1000")
    execute_order(world, Order(aid, OrderSide.BUY, qty))
    rows = position_rows(world)
    assert len(rows) == 1
    r = rows[0]
    assert r[0] == aid and ":" not in r[1]              # (aid, sym)
    assert r[2] > 0                                     # signed qty (long)
    assert abs(r[4] - qty * world.price(aid)) < 1e-6   # value = qty * price
    assert abs(r[5]) < 1e-6                             # unrealized pnl ~0 right after buy
