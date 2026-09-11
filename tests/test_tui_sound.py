"""P5 L2 — the TUI's sound wiring, driven through a real Textual app.

The recorder stands in for winsound / the bell (the suite is muted; see conftest), so what's
under test is the plumbing: boot reads the shared ``sound`` preference, a quick trade cues by
side, a fired resting order cues through ``_advance``, and the ``m`` key both gates playback and
writes the preference the GUI's Appearance ▸ Sound toggle reads.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from textual.widgets import DataTable                # noqa: E402

from trader_pro.cli import TraderApp                 # noqa: E402
from trader_pro.core import (                        # noqa: E402
    World, load_seed_universe, OrderSide, OrderKind, place_pending,
)
from trader_pro.settings import get_setting          # noqa: E402
from trader_pro.sound import NullPlayer              # noqa: E402
from trader_pro.tui import TraderTUI                 # noqa: E402

U = load_seed_universe()


class Recorder:
    def __init__(self):
        self.played: list[str] = []

    def play(self, cue: str) -> None:
        self.played.append(cue)


def _app() -> TraderTUI:
    return TraderTUI(TraderApp(
        World.new(U, 7, profile="Normal", starting_cash=100_000.0), universe=U))


async def _scenario() -> None:
    app = _app()
    assert isinstance(app._player, NullPlayer), "the suite's mute flag was ignored"
    assert app._sound_on, "sound must default on"
    assert app.trader.on_cue is not None, "the TraderApp never got a cue sink"
    rec = Recorder()
    app._player = rec
    async with app.run_test(size=(150, 42)) as pilot:
        board = app.query_one("#board", DataTable)
        board.focus()
        board.move_cursor(row=0)
        await pilot.pause()
        aid = app.cursor_aid
        assert aid, "no asset under the cursor"

        # --- quick trades cue by side ----------------------------------------------------
        app.action_buy_one()
        app.action_sell_one()
        assert rec.played == ["buy", "sell"], rec.played

        # --- a resting order firing through the shared seam ------------------------------
        px = app.trader.world.price(aid)
        place_pending(app.trader.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)
        app.trader._advance(1)
        assert rec.played[-1] == "order_fired", rec.played

        # --- the command line goes through TraderApp too ---------------------------------
        sym = aid.split(":", 1)[1]
        app.trader.execute(f"limit {sym} buy 1 1")
        app.trader.execute("cancel all")
        assert rec.played[-1] == "cancel", rec.played

        # --- `m` gates playback and persists ---------------------------------------------
        n = len(rec.played)
        await pilot.press("m")
        assert app._sound_on is False
        assert get_setting("sound") is False, "toggle not persisted"
        app.action_buy_one()
        app.trader._advance(1)
        assert len(rec.played) == n, "muted, but something played"
        await pilot.press("m")
        assert app._sound_on is True and get_setting("sound") is True
        app.action_sell_one()
        assert len(rec.played) == n + 1 and rec.played[-1] == "sell"
        await pilot.pause()


def test_tui_sound_wiring():
    asyncio.run(_scenario())


async def _scenario_setting() -> None:
    app = _app()
    rec = Recorder()
    app._player = rec
    async with app.run_test(size=(150, 42)) as pilot:
        assert app._sound_on is False, "the GUI's Appearance ▸ Sound toggle was ignored"
        board = app.query_one("#board", DataTable)
        board.focus()
        board.move_cursor(row=0)
        await pilot.pause()
        app.action_buy_one()
        assert rec.played == []
        await pilot.pause()


def test_the_gui_toggle_governs_the_tui_too(tmp_path, monkeypatch):
    """One preference file, both front-ends — switched off in the GUI means off here."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({"sound": False}), encoding="utf-8")
    monkeypatch.setenv("TRADER_PRO_SETTINGS_DIR", str(settings_dir))
    asyncio.run(_scenario_setting())
