"""Orders and execution (V0.2).

Market buy/sell only, executed immediately at the asset's current price. Limit orders,
shorting, and leverage come later (design.md §3.4). Execution is a pure function over a
World so it stays easy to test and, later, to run authoritatively on a server.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid a circular import at runtime
    from .world import World


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Order:
    asset_id: str
    side: OrderSide
    quantity: float

    def to_dict(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "side": self.side.value, "quantity": self.quantity}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Order":
        return Order(d["asset_id"], OrderSide(d["side"]), d["quantity"])


@dataclass(slots=True)
class ExecutionResult:
    filled: bool
    order: Order
    price: float = 0.0
    cash_delta: float = 0.0      # signed change to cash (negative on buy)
    realized_pnl: float = 0.0
    message: str = ""

    def __bool__(self) -> bool:  # `if execute_order(...):`
        return self.filled


def execute_order(world: "World", order: Order) -> ExecutionResult:
    """Execute a market order against `world`, mutating its portfolio on success."""
    if order.quantity <= 0:
        return ExecutionResult(False, order, message="quantity must be positive")
    if not world.has_asset(order.asset_id):
        return ExecutionResult(False, order, message=f"unknown asset {order.asset_id!r}")

    price = world.price(order.asset_id)
    pf = world.portfolio

    if order.side is OrderSide.BUY:
        cost = price * order.quantity
        if cost > pf.cash + 1e-9:
            return ExecutionResult(
                False, order, price=price,
                message=f"insufficient cash: need {cost:.2f}, have {pf.cash:.2f}",
            )
        pf.cash -= cost
        pf.add_long(order.asset_id, order.quantity, price)
        return ExecutionResult(True, order, price=price, cash_delta=-cost,
                               message="filled")

    # SELL
    held = world.portfolio.positions.get(order.asset_id)
    if held is None or order.quantity > held.quantity + 1e-9:
        have = held.quantity if held else 0.0
        return ExecutionResult(
            False, order, price=price,
            message=f"cannot sell {order.quantity}: hold {have} (no shorting in V0.2)",
        )
    pnl = pf.reduce_long(order.asset_id, order.quantity, price)
    proceeds = price * order.quantity
    pf.cash += proceeds
    return ExecutionResult(True, order, price=price, cash_delta=proceeds,
                           realized_pnl=pnl, message="filled")
