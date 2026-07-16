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

from .portfolio import INITIAL_MARGIN_RATIO, MAINTENANCE_MARGIN_RATIO

# Brokerage commission per fill, as a fraction of the traded notional. Charged on BOTH legs of
# a round-trip, so the round-trip cost is ~2x these. A difficulty dial — friction is the direct
# counter to free, high-frequency scalping.
FEE_LEVELS = ("off", "low", "medium", "high", "greedy", "diabolic")
FEE_RATES = {
    "off": 0.0,
    "low": 0.001,      # 0.10%
    "medium": 0.003,   # 0.30%
    "high": 0.006,     # 0.60%
    "greedy": 0.012,   # 1.20%
    "diabolic": 0.025, # 2.50%  (~5% round-trip — only big swings survive it)
}


def fee_rate(level: str) -> float:
    return FEE_RATES.get(level, 0.0)


if TYPE_CHECKING:
    from .world import World


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderKind(str, Enum):
    """A resting order's trigger style (design.md §8.1 trade panel).

    LIMIT fills at a price *better than or equal to* its trigger (buy at/below, sell at/above);
    STOP fires once price *reaches* the trigger in the adverse direction (a buy-stop as price
    rises, a stop-loss sell as it falls). The full truth table is in `PendingOrder.is_triggered`.
    """
    LIMIT = "limit"
    STOP = "stop"


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
    fee: float = 0.0
    message: str = ""

    def __bool__(self) -> bool:
        return self.filled


@dataclass(slots=True)
class PendingOrder:
    """A resting stop/limit order that fills automatically when price crosses its trigger.

    Stored on the Portfolio (so it saves/loads with the player) and checked every advance by
    `process_pending`. `quantity` is always positive; `side` decides whether the eventual fill
    buys or sells — so a stop-loss on a long is a SELL stop, and a stop to cover a short is a
    BUY stop."""
    id: int
    asset_id: str
    side: OrderSide
    quantity: float
    kind: OrderKind
    trigger_price: float
    created_tick: int = 0

    def is_triggered(self, price: float) -> bool:
        """Has `price` crossed the trigger in the fill direction?

        Two of the four (kind, side) combos fire on a *rise* to the trigger, two on a *fall*:
          • rise (price ≥ trigger): SELL limit (take profit), BUY stop (breakout / cover-stop)
          • fall (price ≤ trigger): BUY limit (buy the dip), SELL stop (stop-loss)
        A price sitting exactly on the trigger counts as crossed."""
        rise = (self.kind is OrderKind.LIMIT and self.side is OrderSide.SELL) or \
               (self.kind is OrderKind.STOP and self.side is OrderSide.BUY)
        return price >= self.trigger_price if rise else price <= self.trigger_price

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "asset_id": self.asset_id, "side": self.side.value,
                "quantity": self.quantity, "kind": self.kind.value,
                "trigger_price": self.trigger_price, "created_tick": self.created_tick}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PendingOrder":
        return PendingOrder(
            id=d["id"], asset_id=d["asset_id"], side=OrderSide(d["side"]),
            quantity=d["quantity"], kind=OrderKind(d["kind"]),
            trigger_price=d["trigger_price"], created_tick=d.get("created_tick", 0),
        )


@dataclass(slots=True)
class PlacementResult:
    """Outcome of trying to rest a stop/limit order (parallels ExecutionResult's truthiness)."""
    ok: bool
    order: "PendingOrder | None" = None
    message: str = ""

    def __bool__(self) -> bool:
        return self.ok


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
    fee = fee_rate(getattr(world.config, "fee_level", "off")) * abs(signed) * price
    if fee:
        pf.cash -= fee                    # commission comes straight out of cash ...
        pf.realized_pnl -= fee            # ... and shows up in the net realized tally
    verb = "filled"
    if q0 >= 0 and q1 < 0:
        verb = "opened short"
    elif q0 < 0 and q1 >= 0:
        verb = "covered"
    return ExecutionResult(True, order, price=price, cash_delta=cash_delta,
                           realized_pnl=realized, fee=fee, message=verb)


def place_pending(world: "World", asset_id: str, side: OrderSide, quantity: float,
                  kind: OrderKind, trigger_price: float) -> PlacementResult:
    """Rest a stop/limit order on the portfolio. It touches no cash or positions now — the
    funds/margin check happens only at trigger time, when it goes through `execute_order`.
    Nothing stops you resting an already-in-the-money trigger; it simply fills next advance."""
    if quantity <= 0:
        return PlacementResult(False, message="quantity must be positive")
    if trigger_price <= 0:
        return PlacementResult(False, message="trigger price must be positive")
    if not world.has_asset(asset_id):
        return PlacementResult(False, message=f"unknown asset {asset_id!r}")
    pf = world.portfolio
    order = PendingOrder(id=pf.next_order_id, asset_id=asset_id, side=side, quantity=quantity,
                         kind=kind, trigger_price=trigger_price,
                         created_tick=world.market.tick_index)
    pf.next_order_id += 1
    pf.pending.append(order)
    return PlacementResult(True, order=order, message="resting")


def cancel_pending(world: "World", order_id: int) -> "PendingOrder | None":
    """Remove and return the resting order with `order_id`, or None if there's no such id."""
    pf = world.portfolio
    for i, o in enumerate(pf.pending):
        if o.id == order_id:
            return pf.pending.pop(i)
    return None


def process_pending(world: "World") -> list[ExecutionResult]:
    """Fire any resting orders whose trigger the current price has crossed, in id order.

    A fired order leaves the book whether or not it fills: on success it executes at the
    *current market price* (for a limit, that's at least as good as the trigger); if it can't
    clear the initial-margin check at fire time it is cancelled, carrying the reason. Returns one
    ExecutionResult per fired order — inspect `.filled` to tell a fill from a cancellation.

    Called once per `TraderApp._advance`, so triggers are evaluated on the price at the *end* of
    each advance. In live play (advances of a few ticks) that is effectively every sim-minute; a
    large explicit fast-forward (e.g. +1d) can step over a level only touched intraday — the same
    end-point fidelity the seeded engine uses everywhere else (design.md §5.2)."""
    pf = world.portfolio
    if not pf.pending:
        return []
    results: list[ExecutionResult] = []
    still_resting: list[PendingOrder] = []
    for o in pf.pending:
        if not world.has_asset(o.asset_id) or not o.is_triggered(world.price(o.asset_id)):
            still_resting.append(o)
            continue
        res = execute_order(world, Order(o.asset_id, o.side, o.quantity))
        res.message = (f"{o.kind.value} filled" if res.filled
                       else f"{o.kind.value} cancelled: {res.message}")
        results.append(res)
    pf.pending = still_resting
    return results


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
        pos_qty = abs(pf.positions[aid].quantity)
        price = price_of(aid)
        # Close only enough notional to restore the maintenance requirement (+ a small buffer for
        # fees), rather than dumping the entire largest position over a possibly tiny breach.
        # maintenance_excess = equity − ratio·gross, so the notional to shed is −excess / ratio.
        need_notional = -pf.maintenance_excess(price_of) / MAINTENANCE_MARGIN_RATIO * 1.02
        close_qty = pos_qty if price <= 0 else min(pos_qty, need_notional / price)
        if close_qty <= 0:                       # numerical safety: always make progress
            close_qty = pos_qty
        side = OrderSide.BUY if pf.positions[aid].quantity < 0 else OrderSide.SELL
        res = execute_order(world, Order(aid, side, close_qty))
        res.message = "margin liquidation"
        closures.append(res)
    return closures
