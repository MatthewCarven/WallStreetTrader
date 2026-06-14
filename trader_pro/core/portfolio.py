"""Portfolio, positions, and margin math (V1.3).

A unified signed model handles longs, shorts, and leverage together:

  * `Position.quantity` is **signed** — positive = long, negative = short.
  * `Portfolio.cash` may go **negative** — a negative balance is the margin loan.
  * `equity = cash + Σ quantity·price`. A trade at fair value leaves equity unchanged;
    only *exposure* grows, which is what margin limits constrain.

Two margin ratios (design.md §3.4):
  * INITIAL  — equity must cover this fraction of gross exposure to OPEN/EXTEND a position
    (0.50 → up to 2:1 leverage).
  * MAINTENANCE — if equity falls below this fraction of gross exposure, it's a margin call
    and positions get liquidated (see orders.liquidate_for_margin).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

INITIAL_MARGIN_RATIO = 0.50
MAINTENANCE_MARGIN_RATIO = 0.25

YEAR_TICKS = 365 * 1440          # ticks (minutes) in a simulated year
HARDSHIP_FLOOR = 1000.0          # you can always borrow at least this to get back in

PriceFn = Callable[[str], float]


def loan_apr(leverage_ratio: float) -> float:
    """APR rises with how leveraged the loan makes you (design.md §8.2): a small loan
    against solid assets is cheap; borrowing far beyond your net worth is punitive."""
    if leverage_ratio <= 0.25:
        return 0.06
    if leverage_ratio <= 0.75:
        return 0.12
    if leverage_ratio <= 1.50:
        return 0.22
    return 0.35


@dataclass(slots=True)
class Position:
    """A holding in one asset. `quantity` is signed: + long, − short."""

    quantity: float = 0.0
    avg_cost: float = 0.0     # average entry price of the currently-open quantity

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    def to_dict(self) -> dict[str, Any]:
        return {"quantity": self.quantity, "avg_cost": self.avg_cost}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Position":
        return Position(quantity=d["quantity"], avg_cost=d["avg_cost"])


@dataclass(slots=True)
class Loan:
    principal: float
    balance: float
    apr: float
    opened_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {"principal": self.principal, "balance": self.balance,
                "apr": self.apr, "opened_tick": self.opened_tick}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Loan":
        return Loan(d["principal"], d["balance"], d["apr"], d["opened_tick"])


@dataclass(slots=True)
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    loans: list[Loan] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Fills — the one mutation path (cash is handled by the order executor)
    # ------------------------------------------------------------------ #

    def apply_fill(self, asset_id: str, signed_qty: float, price: float) -> float:
        """Apply a signed fill (+buy / −sell). Handles opening, extending, reducing, and
        flipping a position across zero. Returns realized P&L on any closed quantity."""
        pos = self.positions.get(asset_id) or Position()
        q0 = pos.quantity
        realized = 0.0

        same_dir = (q0 == 0) or ((q0 > 0) == (signed_qty > 0))
        if same_dir:
            # opening or adding in the same direction -> blend the average cost
            total = abs(q0) + abs(signed_qty)
            pos.avg_cost = (pos.avg_cost * abs(q0) + price * abs(signed_qty)) / total
            pos.quantity = q0 + signed_qty
        else:
            # reducing / closing / flipping
            closing = min(abs(signed_qty), abs(q0))
            realized = (price - pos.avg_cost) * closing if q0 > 0 else (pos.avg_cost - price) * closing
            self.realized_pnl += realized
            pos.quantity = q0 + signed_qty
            if abs(signed_qty) > abs(q0):
                pos.avg_cost = price      # flipped sign: remaining is a fresh position

        if abs(pos.quantity) < 1e-9:
            self.positions.pop(asset_id, None)
        else:
            self.positions[asset_id] = pos
        return realized

    # ------------------------------------------------------------------ #
    # Loans (design.md §8.2) — no game-over; borrow your way back in
    # ------------------------------------------------------------------ #

    def loan_balance(self) -> float:
        return sum(l.balance for l in self.loans)

    def borrow_limit(self, net_worth: float) -> float:
        """Most you can borrow right now: ~2x net worth, but always at least the floor."""
        return max(HARDSHIP_FLOOR, 2.0 * max(0.0, net_worth))

    def take_loan(self, amount: float, net_worth: float, tick: int) -> Loan | None:
        """Borrow `amount` if within the limit. APR is set by the resulting leverage."""
        if amount <= 0 or amount > self.borrow_limit(net_worth) + 1e-6:
            return None
        ratio = amount / net_worth if net_worth > 1e-6 else 99.0
        loan = Loan(principal=amount, balance=amount, apr=loan_apr(ratio), opened_tick=tick)
        self.loans.append(loan)
        self.cash += amount
        return loan

    def repay(self, amount: float) -> float:
        """Repay up to `amount` from cash, highest-APR loans first. Returns amount repaid."""
        payable = min(amount, self.cash, self.loan_balance())
        remaining = payable
        for l in sorted(self.loans, key=lambda x: x.apr, reverse=True):
            if remaining <= 0:
                break
            pay = min(remaining, l.balance)
            l.balance -= pay
            remaining -= pay
        self.loans = [l for l in self.loans if l.balance > 1e-6]
        self.cash -= payable
        return payable

    def accrue_interest(self, ticks: int) -> None:
        """Compound loan interest over `ticks` elapsed minutes."""
        if ticks <= 0:
            return
        for l in self.loans:
            l.balance *= (1.0 + l.apr) ** (ticks / YEAR_TICKS)

    def net_worth(self, price_of: PriceFn) -> float:
        """Equity minus outstanding loan debt — the real bottom line."""
        return self.equity(price_of) - self.loan_balance()

        # ------------------------------------------------------------------ #
    # Valuation & margin (all need current prices)
    # ------------------------------------------------------------------ #

    def holdings_value(self, price_of: PriceFn) -> float:
        """Signed market value of all positions (shorts count negative)."""
        return sum(p.quantity * price_of(aid) for aid, p in self.positions.items())

    def gross_exposure(self, price_of: PriceFn) -> float:
        """Total absolute notional across longs and shorts."""
        return sum(abs(p.quantity) * price_of(aid) for aid, p in self.positions.items())

    def equity(self, price_of: PriceFn) -> float:
        return self.cash + self.holdings_value(price_of)

    def margin_debt(self) -> float:
        """Borrowed cash (a negative balance)."""
        return max(0.0, -self.cash)

    def buying_power(self, price_of: PriceFn) -> float:
        """Additional gross exposure the account can still take on."""
        return max(0.0, self.equity(price_of) / INITIAL_MARGIN_RATIO - self.gross_exposure(price_of))

    def maintenance_excess(self, price_of: PriceFn) -> float:
        """Equity above the maintenance requirement. Negative => margin call."""
        return self.equity(price_of) - MAINTENANCE_MARGIN_RATIO * self.gross_exposure(price_of)

    def is_margin_call(self, price_of: PriceFn) -> bool:
        return self.gross_exposure(price_of) > 0 and self.maintenance_excess(price_of) < 0

    def unrealized_pnl(self, price_of: PriceFn) -> float:
        # (price - avg) * quantity works for both signs.
        return sum((price_of(aid) - p.avg_cost) * p.quantity for aid, p in self.positions.items())

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "positions": {aid: p.to_dict() for aid, p in self.positions.items()},
            "loans": [l.to_dict() for l in self.loans],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Portfolio":
        return Portfolio(
            cash=d["cash"],
            realized_pnl=d.get("realized_pnl", 0.0),
            positions={aid: Position.from_dict(pd) for aid, pd in d.get("positions", {}).items()},
            loans=[Loan.from_dict(ld) for ld in d.get("loans", [])],
        )
