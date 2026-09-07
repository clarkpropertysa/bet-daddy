"""A tier that can only ever say UNVALIDATED is decoration.

`compute_edge` takes `settled_contracts` and `mean_clv_cents` and derives the tier from
them. The projection called it with neither, so `assign_tier` had a constant answer and
`sample_n` was always 0 -- grading would have written CLV to SignalResult every week and
nothing would ever have read it back. The same shape as the archiver capturing volume
that no consumer touched.
"""
from decimal import Decimal

import pytest

from pipeline.model.signal import (
    PROVISIONAL_MIN_SETTLED,
    VALIDATED_MIN_SETTLED,
    Tier,
    assign_tier,
    compute_edge,
)


def test_the_default_call_cannot_promote():
    """Pinning the failure: with no history supplied, every signal is UNVALIDATED
    regardless of how good it is. This is correct as a DEFAULT and was the bug as the
    only behaviour."""
    e = compute_edge(0.62, 0.50, 0.52)
    assert e.tier is Tier.UNVALIDATED
    assert e.sample_n == 0


def test_history_promotes():
    e = compute_edge(0.62, 0.50, 0.52,
                     settled_contracts=VALIDATED_MIN_SETTLED,
                     mean_clv_cents=1.4)
    assert e.tier is Tier.VALIDATED
    assert e.sample_n == VALIDATED_MIN_SETTLED

    e = compute_edge(0.62, 0.50, 0.52,
                     settled_contracts=PROVISIONAL_MIN_SETTLED,
                     mean_clv_cents=0.8)
    assert e.tier is Tier.PROVISIONAL


def test_volume_alone_never_promotes():
    """A family with a big sample and negative CLV is disproven, not validated."""
    for clv in (Decimal("-0.01"), Decimal("-5"), Decimal("0")):
        assert assign_tier(VALIDATED_MIN_SETTLED * 10, clv) is Tier.UNVALIDATED


def test_positive_clv_alone_never_promotes():
    """Nor does a good number on three contracts."""
    assert assign_tier(1, Decimal("9.9")) is Tier.UNVALIDATED
    assert assign_tier(PROVISIONAL_MIN_SETTLED - 1, Decimal("9.9")) is Tier.UNVALIDATED


def test_the_thresholds_are_ordered():
    assert PROVISIONAL_MIN_SETTLED < VALIDATED_MIN_SETTLED
