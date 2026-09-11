"""P5 — sound cues: which chirp plays for which event, and how the terminal plays it.

Six short WAVs ship as package data in ``trader_pro/sounds/`` (rendered at build time by
``scripts/render_sounds.py`` from ``sounds/patches/`` — PySynthRack is never a runtime dependency).
This module is the **Qt-free** half of playback:

* :data:`CUES` — the one place the event → file mapping lives. Changing a sound is a line here.
* :func:`fill_cue` / :func:`advance_cue` — turn what the app already knows (an order side, or the
  ``(events, closures, fills)`` triple every ``TraderApp._advance`` returns) into a cue name.
* the terminal players — stdlib ``winsound`` on Windows, the terminal bell elsewhere, and a
  :class:`NullPlayer` for tests and headless runs. The GUI's ``QSoundEffect`` player lives in
  ``gui/sound.py`` because it needs Qt.

**All of them are quiet.** The WAVs are normalised to -18 dBFS at render time, so the events
differ in *character*, not volume — a sound you can leave on for an hour. That is also why an
advance plays **at most one cue**: a crash that triggers a margin call that fires a stop-loss is
one moment, not three chirps stacked on top of each other, and :data:`PRIORITY` decides which.

Playback is best-effort everywhere: a missing file, a dead audio device or a locked-down terminal
must never reach the UI. Players swallow and log, exactly like autosave.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Iterable, Protocol

from ._paths import resource_dir
from .core.orders import OrderSide
from .errlog import log_error

# Package data. From source: <repo>/trader_pro/sounds. Frozen: the same relative path under
# PyInstaller's _MEIPASS (scripts/build_exe.py adds the directory, like data/seeds).
SOUNDS_DIR = resource_dir() / "trader_pro" / "sounds"

# The mapping Matthew settled after auditioning all nine candidates (WORKLOG 2026-09-11):
# buys rise, sells fall, a cancel is barely a note, and the three non-fill events are each a
# recognisable interval rather than a louder blip.
CUES: dict[str, str] = {
    "buy": "fill_c_up.wav",             # your own buy / cover — a rising octave sweep
    "sell": "fill_d_down.wav",          # your own sell / short — the falling mirror
    "cancel": "fill_f_tick.wav",        # a resting order leaving the book unfilled, yours or the engine's
    "order_fired": "order_fired.wav",   # a resting stop/limit filled — a stepped fifth, C5→G5
    "margin_call": "margin_call.wav",   # forced liquidation — a descending tritone
    "black_swan": "black_swan.wav",     # a flash crash — a low thump under a falling sine
}

# When one advance produces several sound-worthy things, the most consequential wins.
PRIORITY: tuple[str, ...] = ("black_swan", "margin_call", "order_fired", "cancel")

MUTE_ENV = "TRADER_PRO_MUTE"       # set (to anything) => every real player becomes a NullPlayer


def cue_path(cue: str) -> Path:
    """Absolute path of the WAV for ``cue``. Raises KeyError for an unknown cue name."""
    return SOUNDS_DIR / CUES[cue]


def sound_enabled() -> bool:
    """The persisted ``sound`` preference — on by default; only an explicit ``false`` is honoured
    (the same reading rule as ``price_flash``, and read at call time so the tests' settings
    override applies)."""
    from .settings import get_setting
    return get_setting("sound") is not False


def muted() -> bool:
    """True when :data:`MUTE_ENV` is set — the test suite's guarantee that a green run is a
    silent one, whatever the preference says."""
    return bool(os.environ.get(MUTE_ENV))


# --------------------------------------------------------------------------- #
# Cue derivation
# --------------------------------------------------------------------------- #

def fill_cue(side_or_verb: "OrderSide | str") -> str:
    """``"buy"`` or ``"sell"`` for a trade the player made themselves.

    Accepts an :class:`OrderSide` or one of the dialog verbs — ``cover`` is a buy and ``short``
    is a sell, which is also what they do to the position, so the sound follows the cash."""
    if isinstance(side_or_verb, OrderSide):
        return "buy" if side_or_verb == OrderSide.BUY else "sell"
    return "buy" if str(side_or_verb).lower() in ("buy", "cover") else "sell"


def advance_cue(events: Iterable, closures: Iterable, fills: Iterable) -> str | None:
    """The single cue an advance earns, or ``None`` for a quiet one.

    Takes the triple ``TraderApp._advance`` returns: market events (a ``flash_crash`` is the
    black swan), forced closures (any => margin call), and fired resting orders (``.filled``
    tells a fill from a cancellation). Highest :data:`PRIORITY` wins."""
    earned: set[str] = set()
    if any(getattr(e, "kind", None) == "flash_crash" for e in events):
        earned.add("black_swan")
    if any(True for _ in closures):
        earned.add("margin_call")
    for r in fills:
        earned.add("order_fired" if r.filled else "cancel")
    for cue in PRIORITY:
        if cue in earned:
            return cue
    return None


# --------------------------------------------------------------------------- #
# Players
# --------------------------------------------------------------------------- #

class Player(Protocol):
    def play(self, cue: str) -> None: ...


class NullPlayer:
    """Plays nothing. Used when muted, and by any front-end without an audio path."""

    def play(self, cue: str) -> None:
        return None


class WinsoundPlayer:
    """Windows: the stdlib ``winsound`` module, asynchronous so the UI never waits on a chirp.

    A new ``PlaySound`` stops whatever was still playing, which is fine — every cue is under
    400 ms and an advance plays at most one. ``SND_NODEFAULT`` keeps a missing file from being
    replaced by the system beep, the one sound this feature must never make."""

    def __init__(self) -> None:
        import winsound
        self._ws = winsound
        self._flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT

    def play(self, cue: str) -> None:
        try:
            path = cue_path(cue)
            if path.is_file():
                self._ws.PlaySound(str(path), self._flags)
        except Exception as exc:                          # best-effort, like autosave
            log_error(exc, f"sound {cue}")


class BellPlayer:
    """Everywhere that isn't Windows: the terminal bell — "where it's a one-liner" (design.md).
    ``bell`` is the front-end's callable (Textual's ``App.bell``), so this module stays free of
    any UI import."""

    def __init__(self, bell: Callable[[], None]) -> None:
        self._bell = bell

    def play(self, cue: str) -> None:
        try:
            self._bell()
        except Exception as exc:
            log_error(exc, f"sound {cue}")


def terminal_player(bell: Callable[[], None] | None = None) -> Player:
    """The right player for a terminal front-end on this platform — or a :class:`NullPlayer`
    when muted or when there is no way to make a sound here."""
    if muted():
        return NullPlayer()
    if sys.platform == "win32":
        try:
            return WinsoundPlayer()
        except Exception as exc:                          # no winsound (odd build) -> bell / silence
            log_error(exc, "sound init")
    if bell is not None:
        return BellPlayer(bell)
    return NullPlayer()
