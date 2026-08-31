"""Named volume multipliers. Every one of these appears in the Why panel."""
import duckdb
import pytest

from pipeline.features.defense import (
    build_pass_defense_grades,
    build_rush_defense_grades,
)
from pipeline.model.adjustments import (
    DEFENSE_MAX_SWING,
    defense_adjustment,
    rest_adjustment,
)

pytestmark = pytest.mark.network

PBP = "data/raw/nflverse/pbp_2025.parquet"
PLAYERS = "data/raw/nflverse/players.parquet"


@pytest.fixture(scope="module")
def grades():
    return build_pass_defense_grades(PBP, PLAYERS), build_rush_defense_grades(PBP)


@pytest.fixture(scope="module")
def teams():
    return [r[0] for r in duckdb.connect().execute(
        f"select distinct defteam from read_parquet('{PBP}') where defteam is not null"
    ).fetchall()]


def test_worse_defence_raises_the_projection(grades):
    """NYJ allowed the most EPA per target in 2025; LAC among the least."""
    pg, rg = grades
    bad = defense_adjustment("NYJ", "rec_yds", pg, rg)
    good = defense_adjustment("LAC", "rec_yds", pg, rg)
    assert bad.multiplier > 1.0
    assert good.multiplier < 1.0
    assert bad.multiplier > good.multiplier


def test_multipliers_are_bounded_by_the_documented_swing(grades, teams):
    """Saturation at ±2σ matters: without it one outlier defence off a thin sample
    produces an unbounded multiplier."""
    pg, rg = grades
    vals = [a.multiplier for t in teams
            if (a := defense_adjustment(t, "rec_yds", pg, rg))]
    assert len(vals) >= 30
    assert min(vals) >= 1.0 - DEFENSE_MAX_SWING - 1e-9
    assert max(vals) <= 1.0 + DEFENSE_MAX_SWING + 1e-9


def test_every_adjustment_is_named_and_explained(grades):
    pg, rg = grades
    a = defense_adjustment("NYJ", "rec_yds", pg, rg)
    assert a.name == "opponent_defense"
    assert "σ" in a.detail and "NYJ" in a.detail


def test_unmodelled_market_gets_no_adjustment(grades):
    pg, rg = grades
    assert defense_adjustment("NYJ", "anytime_td", pg, rg) is None


def test_rush_and_pass_markets_use_different_sides(grades):
    """A team can be good against the pass and bad against the run; using one grade
    for both would silently import the wrong signal."""
    pg, rg = grades
    p = defense_adjustment("NYJ", "rec_yds", pg, rg)
    r = defense_adjustment("NYJ", "rush_yds", pg, rg)
    assert p.multiplier != r.multiplier


def test_rest_states():
    assert rest_adjustment(4, True, False).multiplier < 1.0
    assert rest_adjustment(14, False, True).multiplier > 1.0
    assert rest_adjustment(7, False, False) is None


def test_rest_effects_are_small():
    """Documented rest effects are mostly on efficiency and availability, not on
    opportunity. An uncalibrated volume multiplier that is too large manufactures
    edge, which costs more than failing to find some."""
    assert abs(rest_adjustment(4, True, False).multiplier - 1.0) <= 0.05
    assert abs(rest_adjustment(14, False, True).multiplier - 1.0) <= 0.05


def test_usage_trend_applies_only_the_share_that_persists():
    """Measured, and it overturns what the unconditional numbers suggest.

    As single predictors the season mean beats recency outright (target share
    r2=0.439 against 0.404), which reads as "drop the trend". But the right question is
    whether the deviation adds anything ONCE the season mean is known. Over 1,972
    player-games it does: R2 0.4276 -> 0.4357, coefficient +0.248.

    So recent form is real and roughly a quarter as strong as face value. Only the
    sample-size weight was being applied, so a five-game trend moved the projection
    about four times more than the data supports.
    """
    from pipeline.model.adjustments import (
        USAGE_TREND_MAX_SWING,
        USAGE_TREND_PERSISTENCE,
        usage_trend_adjustment,
    )

    # A trend far beyond the cap, on enough games for full sample weight.
    a = usage_trend_adjustment(2.0, 1.0, 8)
    assert a is not None
    applied = a.multiplier - 1.0
    ceiling = USAGE_TREND_MAX_SWING * USAGE_TREND_PERSISTENCE
    assert applied == pytest.approx(ceiling, abs=1e-6), a.multiplier
    # Under a tenth of the raw 100% deviation.
    assert applied < 0.10


def test_usage_trend_persistence_is_a_shrink_not_a_sign_flip():
    """It must damp the deviation, never invert or amplify it."""
    from pipeline.model.adjustments import USAGE_TREND_PERSISTENCE

    assert 0 < USAGE_TREND_PERSISTENCE <= 1.0


def test_sample_size_and_persistence_both_apply():
    """They answer different questions -- "do I trust this estimate" and "how much of a
    true deviation carries forward" -- so a thin sample must still be shrunk twice."""
    from pipeline.model.adjustments import usage_trend_adjustment

    thin = usage_trend_adjustment(1.4, 1.0, 2)
    full = usage_trend_adjustment(1.4, 1.0, 8)
    assert abs(thin.multiplier - 1.0) < abs(full.multiplier - 1.0)


def test_lean_backtest_is_recorded_and_honest():
    """The game leans have no measured edge, and the number must travel with the code.

    Backtested on 544 out-of-sample games: the model's side covered 46.7% of 272
    disagreements of 3.5+ points, against a 52.4% break-even at -110. Regressed
    against the closing line the model's coefficient is negative, so conditional on
    the market it points the wrong way.

    Pinned so that if anyone later reports these leans as picks, this fails first.
    """
    from pipeline.model.team_rating import LEAN_BACKTEST as L

    assert L["n"] >= 200, "too small a sample to characterise at all"
    assert L["cover_rate"] < L["breakeven"], (
        "if the leans ever clear break-even this constant must be re-measured, not "
        "quietly assumed -- and the UI copy calling them edgeless must change with it"
    )
    assert L["market_corr"] > L["model_corr"], (
        "the market out-predicting the model is the whole reason a disagreement is "
        "not evidence of a mispricing"
    )
