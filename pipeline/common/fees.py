"""Kalshi fee arithmetic.

Verified formula (docs + series metadata fee_type=quadratic, fee_multiplier=1):

    taker fee = ceil(0.07 * C * P * (1 - P))   dollars, rounded UP to the next cent
    maker fee = ceil(0.0175 * C * P * (1 - P)) dollars

Rounding is applied once per order, not per contract. Section 12 of the build spec
requires the exact formula, not an approximation -- at P=0.50 the fee is 1.75c per
contract, which is wider than most prop edges.
"""
from __future__ import annotations

import math
from decimal import ROUND_CEILING, Decimal

CENT = Decimal("0.01")


def _fee(contracts: int, price_dollars: Decimal | float | str, rate: float) -> Decimal:
    p = Decimal(str(price_dollars))
    if not (Decimal(0) <= p <= Decimal(1)):
        raise ValueError(f"price must be in [0,1] dollars, got {p}")
    if contracts < 0:
        raise ValueError("contracts must be non-negative")
    raw = Decimal(str(rate)) * Decimal(contracts) * p * (Decimal(1) - p)
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def taker_fee(contracts: int, price_dollars: Decimal | float | str) -> Decimal:
    """Total taker fee in dollars for an order."""
    return _fee(contracts, price_dollars, 0.07)


def maker_fee(contracts: int, price_dollars: Decimal | float | str) -> Decimal:
    """Total maker fee in dollars for an order."""
    return _fee(contracts, price_dollars, 0.0175)


def marginal_fee_cents(
    price_dollars: Decimal | float | str, maker: bool = False
) -> Decimal:
    """Unrounded per-contract fee in cents.

    Deliberately NOT the per-order rounded figure. The ceil() in taker_fee applies
    once per order, so on a 1-contract order it inflates the true economic rate
    (2.00c vs 1.75c at P=0.50). Edge filters and EV math must use this marginal
    rate; only actual order cost should use taker_fee/maker_fee.
    """
    p = Decimal(str(price_dollars))
    if not (Decimal(0) <= p <= Decimal(1)):
        raise ValueError(f"price must be in [0,1] dollars, got {p}")
    rate = Decimal("0.0175") if maker else Decimal("0.07")
    return (rate * p * (Decimal(1) - p) * 100).quantize(Decimal("0.0001"))


def breakeven_edge_cents(
    price_dollars: Decimal | float | str, maker: bool = False
) -> Decimal:
    """Edge (cents per $1 contract) needed just to cover fees. Alias of marginal rate."""
    return marginal_fee_cents(price_dollars, maker=maker)
