"""Loan system tests (V1.5)."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from trader_pro.core.portfolio import Portfolio, loan_apr  # noqa: E402


def test_apr_rises_with_leverage() -> None:
    assert loan_apr(0.1) < loan_apr(0.5) < loan_apr(1.0) < loan_apr(3.0)


def test_take_loan_adds_cash_and_debt() -> None:
    p = Portfolio(cash=2500.0)
    loan = p.take_loan(1000.0, net_worth=2500.0, tick=0)
    assert loan is not None
    assert p.cash == 3500.0
    assert abs(p.loan_balance() - 1000.0) < 1e-9
    assert loan.apr == loan_apr(1000.0 / 2500.0)


def test_borrow_limit_enforced_with_hardship_floor() -> None:
    p = Portfolio(cash=0.0)
    # Wiped out: net worth 0 -> can still borrow the hardship floor, but not a fortune.
    assert p.take_loan(50_000.0, net_worth=0.0, tick=0) is None
    assert p.take_loan(800.0, net_worth=0.0, tick=0) is not None   # within the floor


def test_interest_accrues_over_time() -> None:
    p = Portfolio(cash=0.0)
    p.take_loan(1000.0, net_worth=5000.0, tick=0)   # 0.2 ratio -> 6% APR
    p.accrue_interest(365 * 1440)                    # one year
    assert abs(p.loan_balance() - 1060.0) < 1.0


def test_repay_reduces_debt_and_cash() -> None:
    p = Portfolio(cash=0.0)
    p.take_loan(1000.0, net_worth=5000.0, tick=0)    # cash -> 1000
    paid = p.repay(400.0)
    assert abs(paid - 400.0) < 1e-9
    assert abs(p.cash - 600.0) < 1e-9
    assert abs(p.loan_balance() - 600.0) < 1e-9


def test_net_worth_nets_out_debt() -> None:
    p = Portfolio(cash=1000.0)
    p.take_loan(1000.0, net_worth=1000.0, tick=0)    # cash 2000, debt 1000
    price_of = lambda a: 0.0
    assert abs(p.net_worth(price_of) - 1000.0) < 1e-9  # 2000 cash - 1000 debt


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f(); print(f"ok  {n}")
    print("all loan tests passed")
