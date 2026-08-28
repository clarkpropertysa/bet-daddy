"""Edge calculation and tiering (Sections 2, 5.6)."""
from decimal import Decimal

import pytest

from pipeline.model.signal import Tier, compute_edge, kelly


def test_fee_erases_a_thin_edge():
    """A 2-point model advantage at midprice is almost entirely eaten by the 1.75c
    fee. This is the central economic fact of the tool: a hit-rate app that ignores
    fees recommends this bet enthusiastically."""
    e = compute_edge(0.52, "0.50")
    assert e.gross_edge_cents == Decimal("2.00")
    assert e.fee_cents == Decimal("1.7500")
    assert e.net_edge_cents == Decimal("0.2500")


def test_edge_smaller_than_fee_is_not_actionable():
    e = compute_edge(0.51, "0.50")
    assert e.net_edge_cents < 0
    assert not e.is_actionable


def test_takes_the_under_when_the_over_is_overpriced():
    """An over that is rich means the under is cheap; both sides are tradeable."""
    e = compute_edge(0.30, "0.45", no_ask_dollars="0.55")
    assert e.side == "no"
    assert e.is_actionable


def test_prices_off_the_ask_not_the_midpoint():
    """Pricing off the midpoint invents edge equal to half the spread, which on thin
    prop markets is most of the apparent edge."""
    tight = compute_edge(0.60, "0.50")
    wide = compute_edge(0.60, "0.55")
    assert wide.net_edge_cents < tight.net_edge_cents


def test_kelly_is_zero_when_model_agrees_with_market():
    assert kelly(Decimal("0.50"), Decimal("0.50")) == 0


def test_kelly_grows_with_edge():
    small = kelly(Decimal("0.55"), Decimal("0.50"))
    big = kelly(Decimal("0.70"), Decimal("0.50"))
    assert 0 < small < big


def test_kelly_never_negative():
    assert kelly(Decimal("0.20"), Decimal("0.50")) == 0


def test_volume_without_positive_clv_is_not_validation():
    """A signal family with a big sample and negative CLV is disproven, not
    validated. Promoting on volume alone is how a tool launders a losing model."""
    e = compute_edge(0.60, "0.50", settled_contracts=900, mean_clv_cents=-0.8)
    assert e.tier is Tier.UNVALIDATED


def test_tier_promotion_requires_both_sample_and_positive_clv():
    assert compute_edge(0.6, "0.5", settled_contracts=250,
                        mean_clv_cents=1.4).tier is Tier.VALIDATED
    assert compute_edge(0.6, "0.5", settled_contracts=80,
                        mean_clv_cents=1.4).tier is Tier.PROVISIONAL
    assert compute_edge(0.6, "0.5", settled_contracts=10,
                        mean_clv_cents=1.4).tier is Tier.UNVALIDATED


def test_everything_starts_unvalidated_with_no_track_record():
    """Week 1 has no history. Signals must not imply one."""
    e = compute_edge(0.60, "0.50")
    assert e.tier is Tier.UNVALIDATED
    assert e.sample_n == 0


def test_rejects_impossible_probability():
    with pytest.raises(ValueError):
        compute_edge(1.5, "0.50")


def test_net_edge_is_gross_minus_fee():
    e = compute_edge(0.65, "0.40")
    assert e.net_edge_cents == e.gross_edge_cents - e.fee_cents
