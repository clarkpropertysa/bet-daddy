"""Kalshi fee formula must be exact, not approximated (Section 12)."""
from decimal import Decimal

import pytest

from pipeline.common.fees import maker_fee, marginal_fee_cents, taker_fee


def test_documented_max_fee_at_midprice():
    # Kalshi documents $1.75 per 100 contracts at P=0.50. This is the anchor value.
    assert taker_fee(100, "0.50") == Decimal("1.75")


def test_fee_is_symmetric_around_midprice():
    assert taker_fee(100, "0.30") == taker_fee(100, "0.70")
    assert taker_fee(100, "0.10") == taker_fee(100, "0.90")


def test_fee_rounds_up_per_order_not_per_contract():
    # 1 contract at 0.50 -> raw 0.0175 -> ceil to 0.02, NOT 0.0175
    assert taker_fee(1, "0.50") == Decimal("0.02")
    # but 100 contracts is 1.75 exactly, not 2.00 -- proving rounding is per-order
    assert taker_fee(100, "0.50") == Decimal("1.75")


def test_marginal_rate_is_unrounded():
    # edge math must use the true marginal rate, not the per-order rounded figure
    assert marginal_fee_cents("0.50") == Decimal("1.7500")
    assert marginal_fee_cents("0.10") == Decimal("0.6300")


def test_maker_is_quarter_of_taker():
    assert maker_fee(10_000, "0.50") == (taker_fee(10_000, "0.50") / 4)


def test_fee_vanishes_at_extremes():
    assert taker_fee(100, "0.00") == Decimal("0.00")
    assert taker_fee(100, "1.00") == Decimal("0.00")


@pytest.mark.parametrize("bad", ["-0.01", "1.01"])
def test_rejects_out_of_range_price(bad):
    with pytest.raises(ValueError):
        taker_fee(1, bad)
