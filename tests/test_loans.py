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


# --- Tier 4: margin carry + aggregate loan limits --- #

def test_margin_debt_accrues_interest() -> None:
    from trader_pro.core.portfolio import MARGIN_APR
    p = Portfolio(cash=-1000.0)                       # $1000 of margin debt
    p.accrue_interest(365 * 1440)                     # one year
    assert abs(p.cash - (-1000.0 * (1.0 + MARGIN_APR))) < 1.0
    assert p.cash < -1000.0                           # leverage now carries a cost


def test_positive_cash_accrues_no_margin_interest() -> None:
    p = Portfolio(cash=5000.0)
    p.accrue_interest(365 * 1440)
    assert p.cash == 5000.0                            # no debt -> nothing charged


def test_loan_limit_is_aggregate_not_per_loan() -> None:
    p = Portfolio(cash=0.0)
    nw = 1000.0                                        # ceiling = max(floor, 2*nw) = 2000
    assert p.take_loan(1500.0, net_worth=nw, tick=0) is not None
    assert p.take_loan(1000.0, net_worth=nw, tick=0) is None    # 1500+1000 > 2000 cap
    assert p.take_loan(500.0, net_worth=nw, tick=0) is not None  # exactly to the cap
    assert p.take_loan(1.0, net_worth=nw, tick=0) is None        # nothing left


def test_stacked_loans_priced_on_total_leverage() -> None:
    p = Portfolio(cash=0.0)
    nw = 1000.0
    l1 = p.take_loan(200.0, net_worth=nw, tick=0)     # total 200 -> ratio 0.2
    l2 = p.take_loan(600.0, net_worth=nw, tick=0)     # total 800 -> ratio 0.8, not its own 0.6
    assert l1.apr == loan_apr(0.2)
    assert l2.apr == loan_apr(0.8) and l2.apr > l1.apr  # tier-dodging by chunks is closed


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f(); print(f"ok  {n}")
    print("all loan tests passed")
