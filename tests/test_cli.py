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


# --- load-flow: saves browser, bare-load, pre-load snapshot --- #

def test_saves_command_lists_slots() -> None:
    import trader_pro.cli as climod
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        climod.SAVES_DIR = Path(d)
        app.execute("save alpha"); app.execute("save beta")
        out = app.execute("saves")
        assert "alpha" in out and "beta" in out


def test_bare_load_browses_not_silently_loads() -> None:
    import trader_pro.cli as climod
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        climod.SAVES_DIR = Path(d)
        app.execute("save alpha")
        out = app.execute("load")                 # no name -> show the browser
        assert "alpha" in out and "loaded" not in out


def test_load_snapshots_current_game_before_replacing() -> None:
    import trader_pro.cli as climod
    from trader_pro.persistence import autosave_path
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        climod.SAVES_DIR = Path(d)
        app.execute("save alpha")
        assert not autosave_path(Path(d)).exists()
        app.execute("load alpha")                 # snapshots current -> autosave, then loads
        assert autosave_path(Path(d)).exists()


# --- Tier 2 safety: never-crash, onboarding, autosave gate --- #

def test_run_rejects_non_numeric_delay() -> None:
    app = _app()
    out = app.execute("run 5 abc")                  # used to raise ValueError and kill the REPL
    assert "usage: run" in out
    assert app.world.market.tick_index == 0         # rejected before advancing


def test_handler_error_is_caught_not_raised() -> None:
    app = _app()

    def _boom(_args):
        raise RuntimeError("boom")

    app._news = _boom                               # a command whose body explodes
    out = app.execute("news")                       # must NOT propagate
    assert "unexpected error" in out


def test_profile_prompt_zero_falls_back_to_normal() -> None:
    import builtins
    import trader_pro.cli as climod

    def _run_prompt(profile_token):
        it = iter([profile_token, "", "", ""])      # profile, seed, cash, fees
        orig = builtins.input
        builtins.input = lambda *a, **k: next(it)
        try:
            return climod._prompt_new_world(U)
        finally:
            builtins.input = orig

    assert _run_prompt("0").config.profile == "Normal"    # the bug: 0 -> PROFILE_NAMES[-1]
    assert _run_prompt("9").config.profile == "Normal"    # out of range -> Normal
    assert _run_prompt("8").config.profile == "Apocalyptic"  # valid max still works
    assert _run_prompt("4").config.profile == "Normal"    # valid default


def test_session_fingerprint_tracks_change() -> None:
    import trader_pro.cli as climod
    app = _app()
    fp0 = climod._session_fingerprint(app)
    app.execute("look BTR")                         # read-only
    assert climod._session_fingerprint(app) == fp0
    app.execute("buy BTR $1000")                    # mutates cash + positions
    assert climod._session_fingerprint(app) != fp0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("all cli tests passed")
