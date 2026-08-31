"""The defensive grid must reach the multiplier, not just the explanation.

features/defense.py computes EPA allowed by air-yard band x receiver position.
`defense_adjustment` collapsed that with `kind, _ = side` and a plain team average,
so the Why panel could report "SEA allows +0.081 EPA per play against passes to TEs"
while the number that actually moved the projection was the team-wide mean.

For a tight end facing Seattle in 2025 those differ by 6.7 points and point in
opposite directions -- the team-wide grade says -0.86 sigma (suppress him), the
tight-end split says +0.83 sigma (boost him).
"""
from pathlib import Path

import pytest

from pipeline.model.adjustments import DEFENSE_MAX_SWING, defense_adjustment

PBP = Path("data/raw/nflverse/pbp_2025.parquet")
PLAYERS = Path("data/raw/nflverse/players.parquet")
pytestmark = pytest.mark.skipif(
    not (PBP.exists() and PLAYERS.exists()), reason="nflverse data not ingested"
)


@pytest.fixture(scope="module")
def grades():
    from pipeline.features.defense import (
        build_pass_defense_grades,
        build_rush_defense_grades,
    )
    return (
        build_pass_defense_grades(str(PBP), str(PLAYERS)),
        build_rush_defense_grades(str(PBP)),
    )


def test_position_changes_the_multiplier(grades):
    """If it does not, the grid is still being averaged away."""
    pg, rg = grades
    by_pos = {
        pos: defense_adjustment("SEA", "rec_yds", pg, rg, position=pos)
        for pos in ("WR", "TE", "RB")
    }
    assert all(a is not None for a in by_pos.values())
    mults = {p: a.multiplier for p, a in by_pos.items()}
    assert len(set(mults.values())) == len(mults), mults


def test_the_split_can_disagree_with_the_team_average(grades):
    """The case that made this worth fixing rather than merely tidying."""
    pg, rg = grades
    team = defense_adjustment("SEA", "rec_yds", pg, rg)
    te = defense_adjustment("SEA", "rec_yds", pg, rg, position="TE")
    assert team.multiplier < 1.0 < te.multiplier, (team.multiplier, te.multiplier)


def test_the_detail_names_the_split_it_used(grades):
    """The explanation has to describe the computation that happened, or this is the
    same failure in a new place."""
    pg, rg = grades
    a = defense_adjustment("SEA", "rec_yds", pg, rg, position="TE")
    assert "TE" in a.detail
    team = defense_adjustment("SEA", "rec_yds", pg, rg)
    assert "TE" not in team.detail


def test_unknown_position_falls_back_to_the_team_grade(grades):
    """A player whose position never resolved still gets a matchup adjustment."""
    pg, rg = grades
    fallback = defense_adjustment("SEA", "rec_yds", pg, rg, position="ZZ")
    team = defense_adjustment("SEA", "rec_yds", pg, rg)
    assert fallback is not None
    assert fallback.multiplier == team.multiplier


def test_multiplier_stays_inside_the_documented_swing(grades):
    pg, rg = grades
    for team in ("SEA", "KC", "BUF", "NYJ"):
        for pos in (None, "WR", "TE", "RB"):
            a = defense_adjustment(team, "rec_yds", pg, rg, position=pos)
            if a:
                assert 1 - DEFENSE_MAX_SWING <= a.multiplier <= 1 + DEFENSE_MAX_SWING


def test_rushing_is_unaffected_by_receiver_position(grades):
    """Position splits are a passing-game concept; a rush grade must ignore them."""
    pg, rg = grades
    a = defense_adjustment("SEA", "rush_yds", pg, rg, position="TE")
    b = defense_adjustment("SEA", "rush_yds", pg, rg)
    assert a.multiplier == b.multiplier
