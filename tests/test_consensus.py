"""The Kalshi-vs-consensus comparison.

Reference only: none of this may feed an edge. The tests that matter most are the ones
pinning the de-vig, because a comparison that forgets to remove the margin from one side
reports the margin itself as divergence -- inventing the finding it exists to detect.
"""
import pytest

from pipeline.features.consensus import (
    american_to_prob,
    compare_game,
    devig_pair,
    summarise,
)


def test_american_odds_convert_both_directions():
    assert american_to_prob(-150) == pytest.approx(0.6)
    assert american_to_prob(+150) == pytest.approx(0.4)
    assert american_to_prob(-110) == pytest.approx(0.5238, abs=1e-4)
    assert american_to_prob(+100) == pytest.approx(0.5)


def test_zero_odds_is_refused():
    """There is no such price. Silently returning 0.5 would look like a coin flip."""
    with pytest.raises(ValueError):
        american_to_prob(0)


def test_standard_juice_devigs_to_a_coin_flip():
    """-110 both ways is the canonical case: 0.5238 each, 4.76% overround, and a true
    price of exactly 0.500. Reporting 0.524 would be reporting the vig as a belief."""
    p = american_to_prob(-110)
    assert p == pytest.approx(0.5238, abs=1e-4)
    a, b = devig_pair(p, p)
    assert a == pytest.approx(0.5)
    assert b == pytest.approx(0.5)


def test_devig_preserves_the_favourite():
    a, b = devig_pair(american_to_prob(-200), american_to_prob(+170))
    assert a + b == pytest.approx(1.0)
    assert a > b


def test_devigged_pair_always_sums_to_one():
    for home, away in [(-110, -110), (-200, +170), (+300, -400), (-1200, +800)]:
        a, b = devig_pair(american_to_prob(home), american_to_prob(away))
        assert a + b == pytest.approx(1.0)


def test_identical_venues_show_zero_divergence():
    """Kalshi quoting the same true prices as the book must read as agreement, even
    though both carry their own margin."""
    c = compare_game(
        kalshi_home_ask=0.52, kalshi_away_ask=0.50,   # ~2c Kalshi spread, 0.51 fair
        vegas_home_ml=-110, vegas_away_ml=-110,        # 4.76% book vig, 0.50 fair
    )
    # Kalshi fair = 0.52/1.02 = 0.5098, Vegas fair = 0.50. Under a point apart.
    assert abs(c.diff_pts) < 1.0


def test_the_exchange_side_is_devigged_too():
    """The bug this test exists to prevent: comparing a de-vigged book price against a
    RAW Kalshi ask reports Kalshi's own spread as divergence."""
    c = compare_game(0.60, 0.50, -110, -110)   # asks sum to 1.10
    naive = (0.60 - 0.50) * 100               # what a raw comparison would report
    assert c.kalshi_prob_home == pytest.approx(0.60 / 1.10)
    assert abs(c.diff_pts) < naive


def test_divergence_is_signed_toward_the_home_team():
    """Kalshi rating the home team higher than the book must be positive, so the sign
    is readable without consulting the source."""
    c = compare_game(0.70, 0.30, -110, -110)
    assert c.diff_pts > 0
    c2 = compare_game(0.30, 0.70, -110, -110)
    assert c2.diff_pts < 0


def test_untradeable_kalshi_price_is_refused():
    """A 0c or 100c ask is an empty book reported as a number, not a price."""
    for bad in (0.0, 1.0, -0.1, 1.4):
        with pytest.raises(ValueError):
            compare_game(bad, 0.5, -110, -110)


def test_overrounds_are_reported_not_hidden():
    """Both margins travel with the comparison: a Kalshi 'divergence' measured against a
    30c-wide book is not the same finding as one against a tight book."""
    c = compare_game(0.55, 0.50, -110, -110)
    assert c.kalshi_overround == pytest.approx(1.05)
    assert c.vegas_overround == pytest.approx(1.0476, abs=1e-4)


def test_summary_reports_absolute_divergence_not_just_signed():
    """Noisy-but-unbiased is the case a signed mean hides, and it is the case that
    matters: it says Kalshi's prices are unreliable, not that they agree."""
    a = compare_game(0.70, 0.30, -110, -110)   # Kalshi high
    b = compare_game(0.30, 0.70, -110, -110)   # Kalshi low by the same amount
    s = summarise([a, b])
    assert s["n"] == 2
    assert s["mean_diff_pts"] == pytest.approx(0.0, abs=1e-6)   # cancels out
    assert s["mean_abs_diff_pts"] > 15                          # does not


def test_empty_summary_reports_nothing_rather_than_zero():
    """No quoted games must not read as 'perfect agreement'."""
    s = summarise([])
    assert s["n"] == 0
    assert s["mean_diff_pts"] is None
    assert s["mean_abs_diff_pts"] is None
