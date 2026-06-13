"""Portfolio and positions (V0.2).

Holds the player's cash and holdings and the realized P&L. Long-only for now; the
fields and execution path are shaped so that shorting and margin (design.md §3.4, V1.3)
slot in later without reworking the data model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Position:
    """A holding in a single asset.

    `quantity` may become negative once short selling lands (V1.3); for now it's >= 0.
    `avg_cost` is the average price paid per unit of the current open quantity.
    """

    quantity: float = 0.0
    avg_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"quantity": self.quantity, "avg_cost": self.avg_cost}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Position":
        return Position(quantity=d["quantity"], avg_cost=d["avg_cost"])


@dataclass(slots=True)
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0

    # ------------------------------------------------------------------ #
    # Mutations (called by the order executor — see orders.py)
    # ------------------------------------------------------------------ #

    def add_long(self, asset_id: str, quantity: float, price: float) -> None:
        """Increase a long position, updating the average cost."""
        pos = self.positions.get(asset_id) or Position()
        new_qty = pos.quantity + quantity
        if new_qty <= 0:
            # Shouldn't happen in long-only V0.2, but stay safe.
            self.positions.pop(asset_id, None)
            return
        pos.avg_cost = (pos.avg_cost * pos.quantity + price * quantity) / new_qty
        pos.quantity = new_qty
        self.positions[asset_id] = pos

    def reduce_long(self, asset_id: str, quantity: float, price: float) -> float:
        """Sell down a long position; returns realized P&L on the sold units."""
        pos = self.positions.get(asset_id)
        if pos is None or quantity > pos.quantity + 1e-9:
            raise ValueError("cannot sell more than held (shorting not enabled in V0.2)")
        pnl = (price - pos.avg_cost) * quantity
        self.realized_pnl += pnl
        pos.quantity -= quantity
        if pos.quantity <= 1e-9:
            self.positions.pop(asset_id, None)
        return pnl

    # ------------------------------------------------------------------ #
    # Valuation (needs current prices, supplied by the World)
    # ------------------------------------------------------------------ #

    def holdings_value(self, price_of) -> float:
        """Market value of all positions. `price_of(asset_id) -> float`."""
        return sum(p.quantity * price_of(aid) for aid, p in self.positions.items())

    def equity(self, price_of) -> float:
        """Total account value = cash + market value of holdings."""
        return self.cash + self.holdings_value(price_of)

    def unrealized_pnl(self, price_of) -> float:
        return sum(
            (price_of(aid) - p.avg_cost) * p.quantity
            for aid, p in self.positions.items()
        )

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "positions": {aid: p.to_dict() for aid, p in self.positions.items()},
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Portfolio":
        return Portfolio(
            cash=d["cash"],
            realized_pnl=d.get("realized_pnl", 0.0),
            positions={
                aid: Position.from_dict(pd) for aid, pd in d.get("positions", {}).items()
            },
        )
