"""Shared display formatting for every front-end (CLI, TUI, GUI).

Pure, stdlib-only string helpers so the three clients render money and share
counts identically. Kept out of ``core`` (which is display-agnostic) but shared
so a formatting fix lands everywhere at once.
"""

from __future__ import annotations

import math


def money(x: float) -> str:
    """Format a dollar amount for display.

    Two deliberate choices over a plain ``f"${x:,.2f}"``:

    * the sign sits *outside* the symbol — ``-$1,234.50``, not ``$-1,234.50`` —
      matching conventional finance formatting at the "you're losing money"
      moments (short value, underwater net worth, realized losses);
    * sub-cent assets keep ~4 significant figures instead of collapsing to
      ``$0.00`` — the game's penny coins (~$0.00002) stay legible and distinct.

    >>> money(1234.5)
    '$1,234.50'
    >>> money(-1234.5)
    '-$1,234.50'
    >>> money(0.5)
    '$0.50'
    >>> money(0.0000212)
    '$0.0000212'
    >>> money(0)
    '$0.00'
    """
    a = abs(float(x))
    sign = "-" if x < 0 else ""
    if a == 0:
        return "$0.00"
    if a >= 0.01:
        return f"{sign}${a:,.2f}"
    decimals = 3 - math.floor(math.log10(a))  # ~4 significant figures
    body = f"{a:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{sign}${body}"


def fmt_qty(q: float) -> str:
    """Format a share / coin count for display.

    Grouped thousands when the amount is whole (``1,000,000`` rather than the
    ``1e+06`` that ``f"{q:g}"`` produces past 6 digits), and a trimmed decimal
    for fractional crypto holdings (``0.5``). Never scientific notation.

    Decimals scale with magnitude so large fractional holdings stay legible:
    2 places at or above one unit, up to 6 for sub-unit crypto. Named
    ``fmt_qty`` rather than ``qty`` because the front-ends already use ``qty``
    as a local variable for the numeric count it formats.

    >>> fmt_qty(1000000)
    '1,000,000'
    >>> fmt_qty(1713205.884447)
    '1,713,205.88'
    >>> fmt_qty(10.5)
    '10.5'
    >>> fmt_qty(0.5)
    '0.5'
    >>> fmt_qty(-1000000)
    '-1,000,000'
    """
    q = float(q)
    if q == int(q):
        return f"{int(q):,}"
    decimals = 2 if abs(q) >= 1 else 6
    return f"{q:,.{decimals}f}".rstrip("0").rstrip(".")


def signed_money(x: float) -> str:
    """Signed dollar amount for P&L displays: ``+$50.00`` / ``-$50.00`` / ``$0.00``.

    P&L columns previously showed ``+50.00`` (no ``$``) beside currency columns that had it;
    this keeps the sign *and* the symbol so a P&L reads as money at a glance.

    >>> signed_money(50)
    '+$50.00'
    >>> signed_money(-50)
    '-$50.00'
    >>> signed_money(0)
    '$0.00'
    """
    return f"+{money(x)}" if x > 0 else money(x)


def abbrev_money(x: float) -> str:
    """Compact money for chart axes and tight labels — ``$1.2M``, ``$52.5k``, ``$110``.

    Chart axis ticks need to stay short; pyqtgraph's default renders large values in
    scientific notation (``1.2e+06``), which is exactly what the rest of the UI avoids.
    Sub-dollar values fall through to :func:`money` so a penny-coin price axis stays legible.

    >>> abbrev_money(1_200_000)
    '$1.2M'
    >>> abbrev_money(900_000)
    '$900k'
    >>> abbrev_money(52_540)
    '$52.5k'
    >>> abbrev_money(152)
    '$152'
    >>> abbrev_money(-1_200_000)
    '-$1.2M'
    """
    a = abs(float(x))
    sign = "-" if x < 0 else ""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            body = f"{a / div:.1f}".rstrip("0").rstrip(".")
            return f"{sign}${body}{suffix}"
    if a >= 1:
        return f"{sign}${a:,.0f}"
    return money(x)
