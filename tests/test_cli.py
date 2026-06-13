"""Headless playthrough of the CLI command logic (V1.1)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro.cli import TraderApp  # noqa: E402
from trader_pro.core import load_seed_universe, World  # noqa: E402

U = load_seed_universe()


def _app(cash=100_000.0):
    return TraderApp(World.new(U, world_seed=20260614, profile="Normal", starting_cash=cash), universe=U)


def test_resolve_symbols_across_kinds() -> None:
    app = _app()
    assert app.resolve("BTR") == "CRYPTO:BTR"
    assert app.resolve("GOVT-30Y") == "BOND:GOVT-30Y"
    assert app.resolve(U.stocks[0].symbol) == f"STOCK:{U.stocks[0].symbol}"
    assert app.resolve("NOPE___") is None


def test_buy_advance_sell_realizes_pnl() -> None:
    app = _app()
    sym = "BTR"
    assert "bought" in app.execute(f"buy {sym} $5000")
    pos = app.world.portfolio.positions[app.resolve(sym)]
    assert pos.quantity > 0
    p0 = app.world.price(app.resolve(sym))
    app.execute("next 4320")                       # advance 3 days; price will move
    p1 = app.world.price(app.resolve(sym))
    assert p1 != p0                                # engine actually moved the price
    out = app.execute(f"sell {sym} all")
    assert "sold" in out
    assert app.resolve(sym) not in app.world.portfolio.positions  # fully closed


def test_buy_dollar_amount_spends_about_that() -> None:
    app = _app()
    cash0 = app.world.portfolio.cash
    app.execute("buy BTR $1000")
    spent = cash0 - app.world.portfolio.cash
    assert abs(spent - 1000.0) < 1.0               # $-denominated buy spends ~$1000


def test_cannot_overspend() -> None:
    app = _app(cash=50.0)
    out = app.execute("buy BTR $999999")
    assert "rejected" in out


def test_time_advances_and_clock_formats() -> None:
    app = _app()
    app.execute("day")
    assert app.world.market.tick_index == 1440
    assert "D1 00:00" in app.header()


def test_save_and_load_round_trip() -> None:
    app = _app()
    app.execute("buy BTR $2000")
    app.execute("hour")
    import trader_pro.cli as climod
    with tempfile.TemporaryDirectory() as d:
        climod.SAVES_DIR = Path(d)
        assert "saved" in app.execute("save unittest")
        app.execute("day")                          # change state
        assert "loaded" in app.execute("load unittest")
    assert app.world.market.tick_index == 60        # back to the saved tick (1 hour)


def test_unknown_command_is_friendly() -> None:
    app = _app()
    assert "unknown command" in app.execute("frobnicate")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all cli tests passed")
