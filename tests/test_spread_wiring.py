"""Game script: the spread must reach the model, with the right sign.

`project_for_game` was called with `None` at both production sites, so
`SPREAD_PASS_RATE_SLOPE` was dead and every pass/run split was the team's season
average whether it was a ten-point favourite or a ten-point dog -- while the comment
beside the call claimed "an underdog throws more".

The sign is the dangerous part. nflverse `spread_line` is positive when the HOME team
is favoured, and `project_for_game` wants positive to mean THIS team is favoured.
Getting it backwards pushes every projection exactly the wrong way, and nothing would
raise.
"""
from pathlib import Path

import pytest

from pipeline.model.project import _spread_index
from pipeline.model.team_volume import TeamVolume, project_for_game

SCHEDULE = Path("data/raw/nflverse/schedules.parquet")


def _tv(pass_rate=0.575, plays=61.3):
    return TeamVolume(team="XX", plays=plays, pass_attempts=plays * pass_rate,
                      rush_attempts=plays * (1 - pass_rate), pass_rate=pass_rate,
                      games_current=0, prior_only=True)


def test_favourites_throw_less_and_underdogs_more():
    """The direction the whole adjustment exists to capture. Measured over 1,084
    team-games: six-point favourites pass on 53.7% of snaps, six-point dogs on 59.5%."""
    fav = project_for_game(_tv(), +7.0)
    dog = project_for_game(_tv(), -7.0)
    assert fav.pass_rate < dog.pass_rate
    assert fav.pass_attempts < dog.pass_attempts
    assert fav.rush_attempts > dog.rush_attempts


def test_no_spread_leaves_the_projection_untouched():
    base = _tv()
    assert project_for_game(base, None) is base


def test_total_plays_are_never_moved():
    """Only the split moves. The game total does not predict play count (r=0.030),
    so inventing a pace effect here would be fabricating signal."""
    for sp in (-14.0, 0.0, 14.0):
        assert project_for_game(_tv(), sp).plays == pytest.approx(61.3)


def test_extreme_spreads_stay_inside_observed_bounds():
    assert 0.30 <= project_for_game(_tv(), +60.0).pass_rate <= 0.80
    assert 0.30 <= project_for_game(_tv(), -60.0).pass_rate <= 0.80


@pytest.mark.skipif(not SCHEDULE.exists(), reason="schedules not ingested")
def test_home_and_away_spreads_are_opposite_and_correctly_signed():
    """Against the real schedule: the home team's spread is `spread_line`, the away
    team's is its negation."""
    idx = _spread_index(str(SCHEDULE), 2026)
    assert idx, "no spreads found for 2026"
    # NE at SEA, week 1: SEA is favoured by 3.5.
    assert idx[("2026-09-09", "SEA")] == pytest.approx(3.5)
    assert idx[("2026-09-09", "NE")] == pytest.approx(-3.5)
    for (day, team), sp in list(idx.items())[:50]:
        assert idx.get((day, team)) == pytest.approx(sp)


@pytest.mark.skipif(not SCHEDULE.exists(), reason="schedules not ingested")
def test_every_game_contributes_both_sides():
    idx = _spread_index(str(SCHEDULE), 2026)
    by_day: dict[str, list[float]] = {}
    for (day, _team), sp in idx.items():
        by_day.setdefault(day, []).append(sp)
    for day, spreads in by_day.items():
        assert sum(spreads) == pytest.approx(0.0, abs=1e-6), day
