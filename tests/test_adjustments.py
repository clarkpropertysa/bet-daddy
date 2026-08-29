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
