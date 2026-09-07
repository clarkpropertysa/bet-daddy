"""Quarterback rates regress; the projection was using them raw.

Cam Ward threw 15 touchdowns on 595 attempts as a rookie -- a 2.52% rate against a
league average of 4.47%. The model reproduced it exactly and projected 0.9 passing
touchdowns for a starting quarterback, driving a 98%-confident UNDER. The same omission
ran the other way for Matthew Stafford at 7.7%.
"""
import numpy as np
import pytest

from pipeline.features.rates import (
    MIN_ATTEMPTS,
    QB_RATE_PRIOR,
    shrink,
    shrink_samples,
)


def test_a_low_outlier_is_pulled_up():
    """The reported case. 0.9 touchdowns a game for a starter is not a projection."""
    out = shrink(0.0252, "pass_td_rate", 595)
    assert out > 0.0252
    assert out == pytest.approx(0.0379, abs=1e-3)
    # 35 attempts a game at the shrunk rate is comfortably over one touchdown
    assert 35 * out > 1.0


def test_a_high_outlier_is_pulled_down():
    """Stafford's 7.7% projected a 47.6-touchdown pace, above his own outlier season."""
    out = shrink(0.077, "pass_td_rate", 400)
    assert out < 0.077
    assert out == pytest.approx(0.056, abs=1e-3)


def test_shrinkage_moves_toward_the_pool_from_either_side():
    pool, _ = QB_RATE_PRIOR["pass_td_rate"]
    assert shrink(pool - 0.02, "pass_td_rate", 500) > pool - 0.02
    assert shrink(pool + 0.02, "pass_td_rate", 500) < pool + 0.02
    assert shrink(pool, "pass_td_rate", 500) == pytest.approx(pool)


def test_non_passers_are_left_alone():
    """THE DANGEROUS CASE. A receiver's attempts_per_game is 0; shrinking it toward the
    pool would hand him 15 attempts a game of a starting quarterback's volume."""
    assert shrink(0.0, "attempts_per_game", 0) == 0.0
    assert shrink(0.0, "completion_rate", 0) == 0.0
    assert shrink(0.0, "pass_td_rate", 12) == 0.0


def test_the_floor_is_where_it_says_it_is():
    assert shrink(0.02, "pass_td_rate", MIN_ATTEMPTS - 1) == 0.02
    assert shrink(0.02, "pass_td_rate", MIN_ATTEMPTS) != 0.02


def test_an_unknown_metric_is_returned_untouched():
    assert shrink(0.5, "not_a_metric", 500) == 0.5
    assert shrink(None, "pass_td_rate", 500) is None


def test_samples_keep_their_shape_and_move_their_mean():
    """The bootstrap draws this player's own completions, so his tail must stay his.
    Only the central tendency is regressed."""
    pool, k = QB_RATE_PRIOR["yards_per_completion"]
    arr = np.array([2.0, 5.0, 9.0, 14.0, 60.0])       # mean 18.0, heavy right tail
    out = shrink_samples(arr, "yards_per_completion", 500)
    assert float(np.mean(out)) == pytest.approx(pool + (18.0 - pool) * k)
    assert float(np.mean(out)) < 18.0                  # a high mean regresses down
    # shape preserved: every ratio between samples is unchanged
    assert np.allclose(out / out[0], arr / arr[0])


def test_samples_below_the_floor_are_untouched():
    arr = np.array([1.0, 2.0, 3.0])
    assert np.allclose(shrink_samples(arr, "yards_per_completion", 5), arr)


def test_empty_or_degenerate_samples_do_not_raise():
    assert len(shrink_samples(np.array([]), "yards_per_completion", 500)) == 0
    zeros = np.zeros(4)
    assert np.allclose(shrink_samples(zeros, "yards_per_completion", 500), zeros)


def test_every_prior_retains_less_than_half():
    """All four measured between k=0.25 and k=0.45. A k above 0.5 would mean the rate
    is more signal than noise, which none of them is."""
    for metric, (pool, k) in QB_RATE_PRIOR.items():
        assert 0.2 <= k <= 0.5, (metric, k)
        assert pool > 0
