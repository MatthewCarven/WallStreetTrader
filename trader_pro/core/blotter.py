"""The blotter: one record per fill, kept on the portfolio (P7, design.md §11 Wave C).

Every fill in the game — a trade the player made, a resting stop/limit that fired, a forced
margin liquidation — goes through `orders.execute_order`, so that is the one place a `Fill` is
written. The list lives on `Portfolio.fills`, serializes with the save (additive: old saves load
with an empty blotter) and is never trimmed: fills happen at human rate, so even a long campaign
is a few thousand rows, and a blotter with holes in it is worse than no blotter.

The record is the trader's view of the fill, not the executor's: `action` says what it *did* to
the position (``buy`` / ``sell`` / ``short`` / ``cover``), `source` says who pulled the trigger,
and `realized_pnl` is gross of `fee` so the two can be reported side by side (`net_pnl` for the
bottom line). The sum of `net_pnl` over the blotter equals `Portfolio.realized_pnl`.

P8 renders this (CLI `history`, TUI screen, GUI dialog + CSV); P9 sums it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .orders import OrderSide

# Who pulled the trigger. "limit"/"stop" are `OrderKind.value` of the resting order that fired.
SOURCES = ("manual", "limit", "stop", "liquidation")
# What the fill did to the position, from the trader's point of view.
ACTIONS = ("buy", "sell", "short", "cover")


def fill_action(side: "OrderSide", qty_before: float) -> str:
    """The trader's word for a fill, from its side and the signed position it hit.

    A BUY against a short is a ``cover`` (even one that flips the position long — the cover is
    the part the trader meant); a SELL from flat or short is a ``short``; the rest are plain
    ``buy`` / ``sell``."""
    if side == "buy":                    # OrderSide is a str enum; no import needed here
        return "cover" if qty_before < 0 else "buy"
    return "sell" if qty_before > 0 else "short"


@dataclass(slots=True)
class Fill:
    tick: int
    asset_id: str
    side: "OrderSide"
    action: str            # one of ACTIONS
    quantity: float        # always positive; `side` carries the direction
    price: float
    fee: float = 0.0
    realized_pnl: float = 0.0   # gross of fee, on any closed quantity
    source: str = "manual"      # one of SOURCES

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def net_pnl(self) -> float:
        """What the fill did to `Portfolio.realized_pnl`."""
        return self.realized_pnl - self.fee

    @property
    def symbol(self) -> str:
        return self.asset_id.split(":", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        return {"tick": self.tick, "asset_id": self.asset_id, "side": self.side.value,
                "action": self.action, "quantity": self.quantity, "price": self.price,
                "fee": self.fee, "realized_pnl": self.realized_pnl, "source": self.source}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Fill":
        from .orders import OrderSide     # local import: orders imports this module
        return Fill(
            tick=d.get("tick", 0), asset_id=d["asset_id"], side=OrderSide(d["side"]),
            action=d.get("action", "buy" if d["side"] == "buy" else "sell"),
            quantity=d["quantity"], price=d["price"], fee=d.get("fee", 0.0),
            realized_pnl=d.get("realized_pnl", 0.0), source=d.get("source", "manual"),
        )
