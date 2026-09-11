"""P5 — the desktop GUI's sound player: ``QSoundEffect`` from QtMultimedia.

QtMultimedia ships inside the PySide6 wheel Trader PRO already depends on, so playing the six
package WAVs costs no new dependency — the point of rendering them at build time instead of
running a synthesiser in-process (design.md, P5). The mapping and the cue derivation are
Qt-free and live in :mod:`trader_pro.sound`; this module only knows how to make Qt play a file.

One ``QSoundEffect`` per cue, created up front so the first fill doesn't pay the decode
(all six load ``Ready`` in ~0.6 s on the dev box, asynchronously, during boot). ``play()`` on an
effect still loading is harmless — Qt drops it — so nothing here ever waits.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl

from ..errlog import log_error
from ..sound import CUES, NullPlayer, Player, cue_path, muted


class QtPlayer:
    """Plays a cue through QtMultimedia. Best-effort: a cue that fails to load or play is logged
    and skipped, never raised — a broken audio stack must not break a trade."""

    def __init__(self, parent: QObject | None = None) -> None:
        self._effects: dict = {}
        try:
            from PySide6.QtMultimedia import QSoundEffect
            for cue in CUES:
                path = cue_path(cue)
                if not path.is_file():
                    continue                              # a missing WAV is a silent cue, not a crash
                eff = QSoundEffect(parent)
                eff.setSource(QUrl.fromLocalFile(str(path)))
                self._effects[cue] = eff
        except Exception as exc:                          # no QtMultimedia / no device: play nothing
            log_error(exc, "sound init")

    @property
    def loaded(self) -> tuple[str, ...]:
        """Cue names that have an effect object (loaded or still loading)."""
        return tuple(self._effects)

    def play(self, cue: str) -> None:
        eff = self._effects.get(cue)
        if eff is None:
            return
        try:
            eff.play()
        except Exception as exc:
            log_error(exc, f"sound {cue}")


def gui_player(parent: QObject | None = None) -> Player:
    """A :class:`QtPlayer`, or a :class:`NullPlayer` when the suite's mute flag is set."""
    if muted():
        return NullPlayer()
    return QtPlayer(parent)
