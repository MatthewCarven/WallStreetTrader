"""Price-flash mechanism — front-end agnostic, Qt-free, Textual-free, clock-injected.

The oldest trick on a trading screen: a price that ticks up flashes green, down flashes red, and
the tint fades out over :data:`FLASH_SECS`. This module is only the *bookkeeping* — which asset
moved, which way, and how bright it should still be. Painting is the front-end's problem, because
"the background behind this cell" means a `QColor` in Qt and a Rich style string in a terminal.

It was born inside ``gui/model.py`` for P4 and moved here for P4b, when the TUI wanted the same
behaviour. Nothing had to change to make that possible, which is the payoff for two decisions
taken while it was still GUI-only:

* **Clock-injected.** Every method takes ``now``. The fade is a function of wall-clock, not of
  frames drawn, so a stall can't leave a flash frozen half-lit — and it is testable at exact
  instants with no event loop of either kind running.
* **Baseline, not history.** It remembers the last price it was *shown*, not the market's. An
  asset it has never seen cannot flash, which keeps view switches and paging silent: you have to
  watch a price move for it to light up.
"""
from __future__ import annotations

FLASH_SECS = 0.7      # a flash fades to nothing this many REAL seconds after the move
FLASH_PEAK = 0.55     # strongest blend toward UP / DOWN, at the instant of the move

# P&L semantics: profit/up green, loss/down red, in every theme — never the themeable accent
# (the P2 split). These mirror ``gui.model.GREEN`` / ``gui.model.RED`` deliberately rather than
# importing them: this module must not depend on a front-end package. A test pins the two
# together so the copies can't drift.
UP = "#2fae4e"
DOWN = "#e5484d"


def blend_hex(base: str, over: str, amount: float) -> str:
    """``base`` mixed ``amount`` (0–1) of the way toward ``over``; both ``#rrggbb``.

    Unlike ``gui.model._scale_hex``, which brightens or dims one colour, this interpolates between
    two — the fade needs an endpoint (whatever the cell's own background is), or a flash on a dark
    board would fade toward black instead of toward the cell it came from."""
    amount = max(0.0, min(1.0, amount))
    chans = []
    for i in (1, 3, 5):
        b, o = int(base[i:i + 2], 16), int(over[i:i + 2], 16)
        chans.append(round(b + (o - b) * amount))
    return "#{:02x}{:02x}{:02x}".format(*chans)


class PriceFlash:
    """Which board rows just moved, and how brightly they should still be glowing."""

    __slots__ = ("duration", "_last", "_hits")

    def __init__(self, duration: float = FLASH_SECS) -> None:
        self.duration = max(0.01, float(duration))       # never divide by zero in alpha()
        self._last: dict[str, float] = {}                # aid -> the price we last displayed
        self._hits: dict[str, tuple[int, float]] = {}    # aid -> (+1 up / -1 down, started at)

    def update(self, prices, now: float) -> None:
        """Take the board's current ``{aid: price}`` and start a flash on everything that moved.

        Assets **absent** from ``prices`` are forgotten — that is what makes paging and view
        switches silent rather than a wall of flashes, since an asset you page back to is unknown
        again and its first sighting only re-seeds the baseline."""
        for aid, price in prices.items():
            prev = self._last.get(aid)
            if prev is not None and price != prev:
                self._hits[aid] = (1 if price > prev else -1, now)
        self._last = dict(prices)
        for aid in [a for a, (_dir, started) in self._hits.items()
                    if a not in self._last or now - started >= self.duration]:
            del self._hits[aid]                          # or the dict grows for the whole session

    def alpha(self, aid: str, now: float) -> float:
        """How much of ``aid``'s flash is left: 1.0 at the move, 0.0 once it has faded out."""
        hit = self._hits.get(aid)
        if hit is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (now - hit[1]) / self.duration))

    def direction(self, aid: str, now: float) -> int:
        """``+1`` up, ``-1`` down, ``0`` when nothing of this asset's flash is left."""
        hit = self._hits.get(aid)
        return hit[0] if hit is not None and self.alpha(aid, now) > 0.0 else 0

    def tint(self, aid: str, now: float, base: str, up: str = UP, down: str = DOWN) -> str | None:
        """``base`` tinted toward ``up`` / ``down`` for a flashing asset, else ``None`` (don't paint).

        The blend peaks at :data:`FLASH_PEAK`, not at the full colour: the digits keep their own
        pale-phosphor foreground, and a saturated cell would drown them for a third of a second."""
        amount = self.alpha(aid, now)
        if amount <= 0.0:
            return None
        return blend_hex(base, up if self._hits[aid][0] > 0 else down, FLASH_PEAK * amount)

    def live(self, now: float) -> bool:
        """True while at least one flash is still fading — the repaint timer's cheap early-out."""
        return any(self.alpha(aid, now) > 0.0 for aid in self._hits)

    def clear(self) -> None:
        """Forget every flash *and* every baseline. Wanted whenever the prices on screen stop
        being comparable with the ones before them — a loaded or new world, or the feature being
        switched back on — where a plain repaint would otherwise light up the entire board."""
        self._last.clear()
        self._hits.clear()
