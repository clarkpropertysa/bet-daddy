"""Edge calculation: model probability vs Kalshi price, net of fees (Section 5.6).

The signal is never a hit rate. It is the difference between the simulated
P(over strike) and what Kalshi is charging, minus the exact fee, expressed in cents
per contract.

Tiering follows DECISIONS.md D1: Kalshi does not retain settled prop markets across
seasons, so there is no historical price series to backtest against. Promotion is
therefore earned FORWARD, on closing line value measured against our own archive.
Every signal starts UNVALIDATED with its sample size attached, and the UI must render
it that way rather than implying a track record that does not exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from pipeline.common.fees import marginal_fee_cents

# Contracts settle at $1.00; prices and edges are expressed in cents of that.
CONTRACT_CENTS = Decimal("100")

# Forward-CLV gates for tier promotion. Deliberately conservative: 200 settled
# contracts is the Section 2 bar, and a positive mean CLV is the evidence that the
# signal family beats the closing line rather than merely looking clever.
PROVISIONAL_MIN_SETTLED = 50
VALIDATED_MIN_SETTLED = 200


class Tier(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    PROVISIONAL = "PROVISIONAL"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True)
class Edge:
    model_prob: Decimal
    market_prob: Decimal
    gross_edge_cents: Decimal
    fee_cents: Decimal
    net_edge_cents: Decimal
    kelly_fraction: Decimal
    side: str            # "yes" or "no"
    tier: Tier
    sample_n: int

    @property
    def is_actionable(self) -> bool:
        return self.net_edge_cents > 0


def implied_prob_from_ask(yes_ask_dollars: Decimal | float | str) -> Decimal:
    """Kalshi quotes in dollars per contract; the ask IS the implied probability.

    Use the ASK, not the last trade or the midpoint: the ask is what you would
    actually pay. Pricing off the midpoint manufactures edge equal to half the
    spread, which on thin prop markets is most of the apparent edge.
    """
    return Decimal(str(yes_ask_dollars))


def kelly(model_prob: Decimal, price: Decimal) -> Decimal:
    """Kelly fraction for a binary contract costing `price` and paying $1.

    b = (1 - price) / price. f* = (p*b - q) / b, floored at zero.
    """
    p = model_prob
    q = Decimal(1) - p
    if price <= 0 or price >= 1:
        return Decimal(0)
    b = (Decimal(1) - price) / price
    f = (p * b - q) / b
    return max(f, Decimal(0))


def assign_tier(settled_contracts: int, mean_clv_cents: Decimal | None) -> Tier:
    """Forward-CLV tiering. Positive CLV is required, not merely a large sample.

    A signal family with 500 settled contracts and negative CLV is not validated --
    it is disproven, and must not be promoted for having volume.
    """
    if mean_clv_cents is None or mean_clv_cents <= 0:
        return Tier.UNVALIDATED
    if settled_contracts >= VALIDATED_MIN_SETTLED:
        return Tier.VALIDATED
    if settled_contracts >= PROVISIONAL_MIN_SETTLED:
        return Tier.PROVISIONAL
    return Tier.UNVALIDATED


def compute_edge(
    model_prob: float | Decimal,
    yes_ask_dollars: float | Decimal | str,
    no_ask_dollars: float | Decimal | str | None = None,
    settled_contracts: int = 0,
    mean_clv_cents: float | Decimal | None = None,
    maker: bool = False,
) -> Edge:
    """Edge on the better side of a market, net of the exact Kalshi fee.

    Both sides are evaluated: an over that is 3c rich means the under is 3c cheap,
    and on Kalshi you can take either. Whichever side survives its own fee wins.
    """
    p_yes = Decimal(str(model_prob))
    if not (Decimal(0) <= p_yes <= Decimal(1)):
        raise ValueError(f"model_prob must be in [0,1], got {p_yes}")

    yes_price = implied_prob_from_ask(yes_ask_dollars)
    # If the no-side ask is not quoted, infer it from the yes bid-ask complement.
    no_price = (Decimal(str(no_ask_dollars)) if no_ask_dollars is not None
                else Decimal(1) - yes_price)

    yes_gross = (p_yes - yes_price) * CONTRACT_CENTS
    yes_fee = marginal_fee_cents(yes_price, maker=maker)
    yes_net = yes_gross - yes_fee

    p_no = Decimal(1) - p_yes
    no_gross = (p_no - no_price) * CONTRACT_CENTS
    no_fee = marginal_fee_cents(no_price, maker=maker)
    no_net = no_gross - no_fee

    if yes_net >= no_net:
        side, prob, price = "yes", p_yes, yes_price
        gross, fee, net = yes_gross, yes_fee, yes_net
    else:
        side, prob, price = "no", p_no, no_price
        gross, fee, net = no_gross, no_fee, no_net

    clv = Decimal(str(mean_clv_cents)) if mean_clv_cents is not None else None
    return Edge(
        model_prob=prob,
        market_prob=price,
        gross_edge_cents=gross,
        fee_cents=fee,
        net_edge_cents=net,
        kelly_fraction=kelly(prob, price),
        side=side,
        tier=assign_tier(settled_contracts, clv),
        sample_n=settled_contracts,
    )
