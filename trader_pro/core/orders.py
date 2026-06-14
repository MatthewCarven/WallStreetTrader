"""Orders, margin-aware execution, and margin-call liquidation (V1.3).

Market orders execute immediately at the current price. BUY adds (covers shorts / goes
long / leverages up); SELL reduces (sells longs / opens or extends a short). The only
constraint on opening or extending exposure is the **initial margin** check; reducing
exposure is always allowed (so you can always de-risk or cover).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from .portfolio import INITIAL_MARGIN_RATIO

if TYPE_CHECKING:
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
    cash_delta: float = 0.0
    realized_pnl: float = 0.0
    message: str = ""

    def __bool__(self) -> bool:
        return self.filled


def execute_order(world: "World", order: Order) -> ExecutionResult:
    """Execute a market order against `world`, mutating its portfolio on success."""
    if order.quantity <= 0:
        return ExecutionResult(False, order, message="quantity must be positive")
    if not world.has_asset(order.asset_id):
        return ExecutionResult(False, order, message=f"unknown asset {order.asset_id!r}")

    price = world.price(order.asset_id)
    pf = world.portfolio
    price_of = world.price_of
    signed = order.quantity if order.side is OrderSide.BUY else -order.quantity

    # Will this increase gross exposure? (opening/extending vs reducing/closing)
    pos = pf.positions.get(order.asset_id)
    q0 = pos.quantity if pos else 0.0
    q1 = q0 + signed
    before = pf.gross_exposure(price_of)
    after = before - abs(q0) * price + abs(q1) * price
    increasing = after > before + 1e-9

    if increasing:
        # A fair-value trade leaves equity unchanged, so just check equity vs the new gross.
        if pf.equity(price_of) < INITIAL_MARGIN_RATIO * after - 1e-6:
            return ExecutionResult(
                False, order, price=price,
                message=(f"insufficient buying power: need equity "
                         f"{INITIAL_MARGIN_RATIO * after:,.2f}, have {pf.equity(price_of):,.2f}"),
            )

    realized = pf.apply_fill(order.asset_id, signed, price)
    cash_delta = -signed * price          # buy: cash down; sell/short: cash up
    pf.cash += cash_delta
    verb = "filled"
    if q0 >= 0 and q1 < 0:
        verb = "opened short"
    elif q0 < 0 and q1 >= 0:
        verb = "covered"
    return ExecutionResult(True, order, price=price, cash_delta=cash_delta,
                           realized_pnl=realized, message=verb)


def liquidate_for_margin(world: "World") -> list[ExecutionResult]:
    """Force-close positions (largest exposure first) until the account clears its
    maintenance requirement or runs out of positions. Returns the forced closures.

    This is what gives leverage and shorts real teeth (design.md §3.4) and is the hook the
    crash-cascade system (V1.4) will lean on."""
    pf = world.portfolio
    price_of = world.price_of
    closures: list[ExecutionResult] = []
    guard = 0
    while pf.is_margin_call(price_of) and pf.positions and guard < 10_000:
        guard += 1
        aid = max(pf.positions, key=lambda a: abs(pf.positions[a].quantity) * price_of(a))
        qty = abs(pf.positions[aid].quantity)
        side = OrderSide.BUY if pf.positions[aid].quantity < 0 else OrderSide.SELL
        res = execute_order(world, Order(aid, side, qty))
        res.message = "margin liquidation"
        closures.append(res)
    return closures
