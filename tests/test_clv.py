"""Closing line value and settlement P&L.

Prices here are constructed arithmetic inputs, not claimed sports facts -- these
tests check the money math, not any real market's history.
"""
from decimal import Decimal

import pytest

from pipeline.backtest.clv import compute_clv_cents, settle_pnl_cents


def test_yes_gains_clv_when_price_rises():
    """Bought at 40c, closed at 47c: the market moved toward the position by 7c."""
    assert compute_clv_cents("0.40", "0.47", "yes") == Decimal("7.00")


def test_yes_loses_clv_when_price_falls():
    assert compute_clv_cents("0.40", "0.35", "yes") == Decimal("-5.00")


def test_no_side_sign_is_inverted():
    """A NO holder profits when the yes price falls, so the same move that hurts a
    YES helps a NO. Getting this sign wrong inverts the entire track record."""
    assert compute_clv_cents("0.40", "0.35", "no") == Decimal("5.00")
    assert compute_clv_cents("0.40", "0.47", "no") == Decimal("-7.00")


def test_clv_is_zero_when_price_does_not_move():
    assert compute_clv_cents("0.55", "0.55", "yes") == Decimal("0.00")


def test_clv_does_not_depend_on_outcome():
    """CLV is measured on price movement alone. That is why it is readable after
    dozens of contracts rather than hundreds of settlements."""
    assert compute_clv_cents("0.30", "0.40", "yes") == Decimal("10.00")


def test_rejects_bad_side():
    with pytest.raises(ValueError):
        compute_clv_cents("0.4", "0.5", "over")


def test_winning_yes_pnl_is_payout_minus_cost_and_fee():
    # bought yes at 40c, settles yes: 100 payout - 40 cost - 1.68 fee = 58.32
    assert settle_pnl_cents("0.40", "yes", "yes", "1.68") == Decimal("58.32")


def test_losing_yes_pnl_is_negative_cost_and_fee():
    assert settle_pnl_cents("0.40", "yes", "no", "1.68") == Decimal("-41.68")


def test_no_side_cost_is_the_complement():
    """A NO at a 40c yes-price costs 60c, not 40c."""
    assert settle_pnl_cents("0.40", "no", "no", "1.68") == Decimal("38.32")
    assert settle_pnl_cents("0.40", "no", "yes", "1.68") == Decimal("-61.68")


def test_fee_always_reduces_pnl():
    with_fee = settle_pnl_cents("0.50", "yes", "yes", "1.75")
    without = settle_pnl_cents("0.50", "yes", "yes", "0")
    assert with_fee == without - Decimal("1.75")


def test_rejects_bad_result():
    with pytest.raises(ValueError):
        settle_pnl_cents("0.4", "yes", "push", "1.0")
