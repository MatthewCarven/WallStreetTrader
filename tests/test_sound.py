"""P5 L2 — sound cues: the mapping, the derivation, the hook on TraderApp, and both players.

Everything here runs **silent**: ``conftest.py`` sets ``TRADER_PRO_MUTE`` so real players are
never built, and the tests that need a player install a recorder. The one place a real backend
is exercised is the ``winsound`` test, which swaps the module for a stub — the shape of the call
is what's under test, not the speaker. The GUI's QtMultimedia player is proven in
``test_gui_sound.py`` by *loading* the WAVs, never playing them.

What's worth defending: every cue name has a real, quiet, short WAV; one advance never plays more
than one cue and the most consequential wins; a player that raises can't break a trade; and the
plain REPL (no player attached) stays silent without anyone having to think about it.
"""
from __future__ import annotations

import array
import math
import sys
import types
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trader_pro import sound as S                                        # noqa: E402
from trader_pro.cli import TraderApp                                     # noqa: E402
from trader_pro.core import (                                            # noqa: E402
    AssetKind, MarketEngine, OrderKind, OrderSide, World, load_seed_universe, make_asset_id,
    place_pending,
)

U = load_seed_universe()


class Recorder:
    def __init__(self):
        self.played: list[str] = []

    def play(self, cue: str) -> None:
        self.played.append(cue)


def _world(cash=100_000.0, seed=20260614):
    w = World.new(U, seed, starting_cash=cash)
    MarketEngine(w)
    return w


def _stock():
    return make_asset_id(AssetKind.STOCK, U.stocks[0].symbol)


# --------------------------------------------------------------------------- #
# The package data
# --------------------------------------------------------------------------- #

def test_every_cue_has_a_short_quiet_wav_in_the_package():
    """The six winners moved out of the audition tray into trader_pro/sounds/ — and stayed
    within the L1 contract: 16-bit mono, under 400 ms, peak at -18 dBFS (±0.1 dB)."""
    for cue in S.CUES:
        path = S.cue_path(cue)
        assert path.is_file(), f"{cue}: {path} missing"
        with wave.open(str(path)) as w:
            assert (w.getnchannels(), w.getsampwidth()) == (1, 2), cue
            frames = w.readframes(w.getnframes())
            assert w.getnframes() / w.getframerate() < 0.4, cue
        samples = array.array("h", frames)
        peak = max(abs(s) for s in samples) / 32768.0
        assert abs(20 * math.log10(peak) + 18.0) < 0.1, f"{cue}: peak {20 * math.log10(peak):.2f} dBFS"


def test_the_mapping_is_the_one_matthew_settled():
    assert S.CUES["buy"] == "fill_c_up.wav"          # buys rise
    assert S.CUES["sell"] == "fill_d_down.wav"       # sells fall
    assert S.CUES["cancel"] == "fill_f_tick.wav"     # the tick, barely a note
    assert set(S.CUES) == {"buy", "sell", "cancel", "order_fired", "margin_call", "black_swan"}
    assert set(S.PRIORITY) <= set(S.CUES)


def test_cue_path_rejects_unknown_names():
    with pytest.raises(KeyError):
        S.cue_path("klaxon")


# --------------------------------------------------------------------------- #
# Cue derivation
# --------------------------------------------------------------------------- #

def test_fill_cue_follows_the_cash():
    assert S.fill_cue(OrderSide.BUY) == "buy" and S.fill_cue(OrderSide.SELL) == "sell"
    assert S.fill_cue("buy") == "buy" and S.fill_cue("cover") == "buy"      # cover is a buy
    assert S.fill_cue("sell") == "sell" and S.fill_cue("short") == "sell"   # short is a sell
    assert S.fill_cue("SHORT") == "sell"


def _ev(kind):
    return SimpleNamespace(kind=kind)


def _fill(filled):
    return SimpleNamespace(filled=filled)


def test_advance_cue_is_quiet_when_nothing_happened():
    assert S.advance_cue([], [], []) is None
    assert S.advance_cue([_ev("earnings"), _ev("sector")], [], []) is None   # ordinary news is silent


def test_advance_cue_one_per_kind():
    assert S.advance_cue([_ev("flash_crash")], [], []) == "black_swan"
    assert S.advance_cue([], [object()], []) == "margin_call"
    assert S.advance_cue([], [], [_fill(True)]) == "order_fired"
    assert S.advance_cue([], [], [_fill(False)]) == "cancel"


def test_advance_cue_plays_at_most_one_and_the_worst_wins():
    """A crash that triggers a margin call that fires a stop-loss is one moment, not three."""
    assert S.advance_cue([_ev("flash_crash")], [object()], [_fill(True), _fill(False)]) == "black_swan"
    assert S.advance_cue([_ev("rate")], [object()], [_fill(True)]) == "margin_call"
    assert S.advance_cue([], [], [_fill(False), _fill(True), _fill(False)]) == "order_fired"


# --------------------------------------------------------------------------- #
# The hook on TraderApp
# --------------------------------------------------------------------------- #

def test_the_plain_repl_has_no_player_and_stays_silent():
    app = TraderApp(world=_world())
    assert app.on_cue is None
    app.execute("buy BTR $100")                     # nothing to raise into; must not blow up
    app.cue("buy")
    app.cue(None)


def test_command_line_fills_and_cancels_cue():
    app = TraderApp(world=_world())
    rec = Recorder()
    app.on_cue = rec.play
    app.execute("buy BTR $100")
    app.execute("sell BTR all")
    app.execute("short BTR $100")
    app.execute("cover BTR")
    app.execute("buy BTR $99999999")                # rejected — no sound for a non-fill
    app.execute("limit BTR buy 1 1")                # resting is not a fill: silent
    assert rec.played == ["buy", "sell", "sell", "buy"]
    app.execute("cancel 1")
    app.execute("cancel 99")                        # no such order: silent
    app.execute("limit BTR buy 1 1")
    app.execute("limit BTR buy 1 2")
    app.execute("cancel all")                       # one tick for the lot, not one per order
    app.execute("cancel all")                       # nothing left: silent
    assert rec.played == ["buy", "sell", "sell", "buy", "cancel", "cancel"]


def test_a_fired_resting_order_cues_through_the_shared_seam():
    app = TraderApp(world=_world())
    rec = Recorder()
    app.on_cue = rec.play
    aid = _stock(); px = app.world.price(aid)
    place_pending(app.world, aid, OrderSide.BUY, 2, OrderKind.LIMIT, px * 1.5)   # fires next advance
    app._advance(1)
    assert rec.played == ["order_fired"]
    app._advance(1)                                 # nothing resting now: a quiet advance
    assert rec.played == ["order_fired"]


def test_a_resting_order_cancelled_at_fire_time_ticks():
    app = TraderApp(world=_world(cash=1_000.0))
    rec = Recorder()
    app.on_cue = rec.play
    aid = _stock(); px = app.world.price(aid)
    place_pending(app.world, aid, OrderSide.BUY, 1e9, OrderKind.STOP, px * 0.5)  # unaffordable
    app._advance(1)
    assert rec.played == ["cancel"]


def test_margin_call_and_black_swan_cue_from_the_seam(monkeypatch):
    """Neither is cheap to provoke for real, and neither needs to be: the seam is what's under
    test. A fake closure list and a fake flash-crash event stand in — and when both land in the
    same advance the swan wins, per PRIORITY."""
    import trader_pro.cli as cli

    app = TraderApp(world=_world())
    rec = Recorder()
    app.on_cue = rec.play
    monkeypatch.setattr(cli, "liquidate_for_margin", lambda world: [object()])
    app._advance(1)
    assert rec.played == ["margin_call"]
    monkeypatch.setattr(app.engine.events, "fired_between", lambda t0, t1: [_ev("flash_crash")])
    app._advance(1)
    assert rec.played == ["margin_call", "black_swan"]


def test_a_player_that_raises_never_breaks_a_trade(tmp_path, monkeypatch):
    def boom(cue):
        raise RuntimeError("no audio device")

    app = TraderApp(world=_world())
    app.on_cue = boom
    out = app.execute("buy BTR $100")
    assert "bought" in out                          # the trade happened; the noise didn't
    assert app.world.portfolio.positions


# --------------------------------------------------------------------------- #
# Preference + players
# --------------------------------------------------------------------------- #

def test_sound_preference_is_on_unless_explicitly_off(tmp_path, monkeypatch):
    from trader_pro.settings import update_settings
    assert S.sound_enabled()                        # no file at all
    update_settings({"sound": "yes please"})
    assert S.sound_enabled()                        # junk value: keep the default
    update_settings({"sound": False})
    assert not S.sound_enabled()
    update_settings({"sound": True})
    assert S.sound_enabled()


def test_muted_env_yields_a_null_player_everywhere():
    assert S.muted()                                # conftest sets it for the whole suite
    assert isinstance(S.terminal_player(lambda: None), S.NullPlayer)
    S.terminal_player().play("buy")                 # and it is harmless to call


def test_winsound_player_on_windows(monkeypatch):
    """Swap the stdlib module for a stub: asserts the call shape (file, async, no default beep)
    without ever reaching a speaker."""
    calls = []
    stub = types.SimpleNamespace(
        SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4,
        PlaySound=lambda path, flags: calls.append((path, flags)),
    )
    monkeypatch.setitem(sys.modules, "winsound", stub)
    monkeypatch.delenv("TRADER_PRO_MUTE")
    monkeypatch.setattr(sys, "platform", "win32")
    player = S.terminal_player(bell=lambda: None)
    assert isinstance(player, S.WinsoundPlayer)
    player.play("margin_call")
    assert calls == [(str(S.cue_path("margin_call")), 1 | 2 | 4)]
    player.play("klaxon")                           # unknown cue: logged, not raised
    assert len(calls) == 1


def test_bell_player_elsewhere(monkeypatch):
    rings = []
    monkeypatch.delenv("TRADER_PRO_MUTE")
    monkeypatch.setattr(sys, "platform", "linux")
    player = S.terminal_player(bell=lambda: rings.append(1))
    assert isinstance(player, S.BellPlayer)
    player.play("buy")
    player.play("black_swan")
    assert rings == [1, 1]
    assert isinstance(S.terminal_player(bell=None), S.NullPlayer)   # no bell, no sound
