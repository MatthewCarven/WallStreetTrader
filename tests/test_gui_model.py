"""Pure unit tests for the GUI's Qt-free helpers (no PySide6 needed)."""
from pathlib import Path

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
    trader, resumed, from_backup = boot()          # 3-tuple since P3 (autosave generations)
    assert trader.world is not None
    assert isinstance(resumed, bool)
    assert isinstance(from_backup, bool)
    assert not (from_backup and not resumed)       # a backup resume is still a resume


def test_boot_reports_a_backup_resume(monkeypatch):
    """boot()'s third value is the only thing that tells the player their game rewound, and it
    is a *comparison* — it silently reads False if the wiring points at the wrong path."""
    import trader_pro.gui.model as M

    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    live, backup = Path("/saves/autosave.world"), Path("/saves/autosave.1.world")
    monkeypatch.setattr(M, "has_autosave", lambda *a, **k: True)
    monkeypatch.setattr(M, "autosave_path", lambda *a, **k: live)

    monkeypatch.setattr(M, "load_autosave", lambda *a, **k: (world, live))
    assert M.boot()[1:] == (True, False)                # resumed from the live slot

    monkeypatch.setattr(M, "load_autosave", lambda *a, **k: (world, backup))
    assert M.boot()[1:] == (True, True)                 # ...and from a generation behind it

    def _dead(*a, **k):
        raise FileNotFoundError("no readable autosave")
    monkeypatch.setattr(M, "load_autosave", _dead)
    trader, resumed, from_backup = M.boot()
    assert (resumed, from_backup) == (False, False)     # dead chain -> a fresh world, no warning
    assert trader.world.market.tick_index == 0


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


def test_change_columns_are_dashes_until_the_window_is_real():
    """P18: on a young world every lookback clamps to tick 0, so 1D / 7D / 31D all showed the
    *same* number — correct, but indistinguishable from a broken column. Each window stays a
    dim `—` until the world is actually old enough for it, then lights up."""
    from trader_pro.gui.model import chg_col, has_window
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    eng = trader.engine
    aid = kind_ids(world, AssetKind.STOCK)[0]

    trader._advance(31)                                  # 31 minutes in — the screenshot's world
    assert not has_window(world, 1)
    ctx = row_ctx(world, eng, aid)
    assert ctx.chg is None and ctx.chg7d is None and ctx.chg31d is None
    for col in ("chg", "chg7d", "chg31d"):
        c = cell(ctx, col)
        assert c.text == "—" and c.color == DIM

    trader._advance(2 * 1440)                            # past a day: 1D lights up, 7D/31D don't
    assert has_window(world, 1) and not has_window(world, 7)
    ctx = row_ctx(world, eng, aid)
    assert ctx.chg == chg_col(world, eng, aid, 1) is not None
    assert cell(ctx, "chg").text.endswith("%")
    assert cell(ctx, "chg7d").text == "—" and cell(ctx, "chg31d").text == "—"

    trader._advance(40 * 1440)                           # past a month: all three are real
    ctx = row_ctx(world, eng, aid)
    assert all(cell(ctx, c).text.endswith("%") for c in ("chg", "chg7d", "chg31d"))
    # …and they no longer agree, which was the whole complaint
    assert len({cell(ctx, c).text for c in ("chg", "chg7d", "chg31d")}) == 3


def test_sorters_still_see_a_number_on_a_young_world():
    """The `—` is display-only. movers and sort-by-1D% rank by chg_pct, which keeps returning
    change-since-open on a young world — blanking *that* would break the ordering."""
    from trader_pro.gui.model import movers_ids, ticker_text
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Volatile", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    eng = trader.engine
    trader._advance(31)                                  # too young for any window
    stocks = kind_ids(world, AssetKind.STOCK)
    ids, _ = visible_ids(world, eng, view_source=stocks, owned_only=False, sort_by_change=True,
                         watch=default_watchlist(world), view_page=0, page_size=25)
    chgs = [chg_pct(world, eng, a, 1) for a in ids]
    assert chgs == sorted(chgs, reverse=True)            # still a real ordering
    assert any(c != 0.0 for c in chgs)                   # …on real, non-blank numbers
    m = movers_ids(world, eng, n=8)                      # 8 gainers + 8 losers, deduped
    assert len(m) == 16 and m == list(dict.fromkeys(m))
    tape = ticker_text(world, eng, default_watchlist(world))
    assert "▲" in tape or "▼" in tape                    # the tape arrow still resolves


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
    # empty buy => spend cash on hand only, NOT the 2:1 buying power
    assert abs(trade_quantity(world, aid, "buy", "") - world.portfolio.cash / price) < 1e-6
    # empty short still uses full buying power (2:1 margin)
    bp = world.portfolio.buying_power(world.price_of)
    assert abs(trade_quantity(world, aid, "short", "") - bp / price) < 1e-6
    assert trade_quantity(world, aid, "sell", "") == 0.0                      # nothing held
    assert trade_quantity(world, aid, "sell", "all") == 0.0
    assert trade_quantity(world, aid, "buy", "abc") == 0.0                    # garbage => 0


def test_trade_quantity_buy_reserves_for_fees():
    from trader_pro.core.orders import fee_rate
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0, fee_level="high")
    aid = kind_ids(world, AssetKind.CRYPTO)[0]
    price = world.price(aid)
    # a max buy leaves room for the commission, so total outlay == cash (no margin)
    expected = world.portfolio.cash / (price * (1 + fee_rate("high")))
    assert abs(trade_quantity(world, aid, "buy", "") - expected) < 1e-6


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


def test_movers_ids_and_ticker_text():
    from trader_pro.gui.model import movers_ids, ticker_text
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    trader._advance(2 * 1440)                           # let prices move
    m = movers_ids(world, trader.engine, n=8)
    assert m == list(dict.fromkeys(m))                  # deduped, order preserved
    assert all(world.has_asset(a) for a in m)
    tape = ticker_text(world, trader.engine, default_watchlist(world))
    assert ("▲" in tape or "▼" in tape) and len(tape) > 0


def test_ticker_keeps_sub_cent_precision():
    """P19: the tape hardcoded `:,.2f`, so every penny coin read `FRG 0.00` while the board
    right below it showed $0.0000001834. It must use money(), which keeps ~4 sig figs."""
    from trader_pro.fmt import money
    from trader_pro.gui.model import ticker_text
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    watch = default_watchlist(world)[:18]               # only the head of the list reaches the tape
    cheap = min(watch, key=world.price)
    assert world.price(cheap) < 0.01, "seed universe no longer has a sub-cent coin to test with"
    tape = ticker_text(world, trader.engine, watch)
    sym = cheap.split(":", 1)[1]
    assert f"{sym} {money(world.price(cheap))} " in tape
    assert f"{sym} 0.00 " not in tape                   # the pre-fix rendering


def test_event_and_closure_entry():
    from trader_pro.core import ExecutionResult, MarketEvent, Order, OrderSide
    from trader_pro.gui.model import closure_entry, event_entry
    up = MarketEvent(100, "earnings", "asset", "STOCK:AAPL", 0.05, 1440.0, "AAPL beats")
    text, color = event_entry(up)
    assert "AAPL beats" in text and color == GREEN
    dn = MarketEvent(100, "earnings", "asset", "STOCK:AAPL", -0.05, 1440.0, "AAPL misses")
    assert event_entry(dn)[1] == RED
    res = ExecutionResult(True, Order("CRYPTO:BTR", OrderSide.BUY, 0.5), price=60000.0,
                          realized_pnl=-100.0)
    ctext, ccolor = closure_entry(res)
    assert "MARGIN CALL" in ctext and "BTR" in ctext and ccolor == RED


def test_fill_entry():
    from trader_pro.core import ExecutionResult, Order, OrderSide
    from trader_pro.gui.model import GREEN_HI, fill_entry
    # a buy: green, uppercased verb, symbol & price; fee appended when non-zero
    res = ExecutionResult(True, Order("STOCK:AAPL", OrderSide.BUY, 10), price=150.0, fee=1.5)
    text, color = fill_entry("buy", 10, "AAPL", res)
    assert text.startswith("BUY 10 AAPL @") and "fee" in text and color == GREEN
    # a sell that realizes P&L: red, "realized" shown
    res2 = ExecutionResult(True, Order("STOCK:AAPL", OrderSide.SELL, 10), price=160.0,
                           realized_pnl=95.0)
    t2, c2 = fill_entry("sell", 10, "AAPL", res2)
    assert "SELL 10 AAPL @" in t2 and "realized" in t2 and c2 == RED
    # verb -> colour mapping matches the TradeDialog buttons for short / cover
    assert fill_entry("short", 1, "AAPL", res2)[1] == AMBER
    assert fill_entry("cover", 1, "AAPL", res)[1] == GREEN_HI


def test_save_info_line(tmp_path):
    from trader_pro.gui.model import save_info_line
    from trader_pro.persistence import list_saves, save_game, slot_path
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    save_game(world, slot_path("mygame", tmp_path), label="mygame")
    infos = list_saves(tmp_path)
    assert infos
    line = save_info_line(infos[0])
    assert "mygame" in line and "net worth" in line and "Normal" in line


def test_prediction_summary():
    from trader_pro.core import make_prediction
    from trader_pro.core.engine import DAY
    from trader_pro.gui.model import prediction_summary
    uni = load_seed_universe()
    world = World.new(uni, world_seed=1, profile="Normal", starting_cash=5000.0)
    trader = TraderApp(world, universe=uni)
    aid = kind_ids(world, AssetKind.CRYPTO)[0]
    pred = make_prediction(world, trader.engine, aid, DAY)
    s = prediction_summary(pred)
    assert "FORECAST" in s and aid.split(":", 1)[1] in s and ("UP" in s or "DOWN" in s)
