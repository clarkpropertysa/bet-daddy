"""Rest/schedule context, asserted against the real 2026 NFL schedule."""
import duckdb
import pytest

from pipeline.features.rest import build
from pipeline.ingest.nflverse import fetch

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def rest():
    return build(fetch("schedules"), season=2026)


@pytest.fixture(scope="module")
def con(rest):
    c = duckdb.connect()
    c.register("rest", rest)
    return c


def test_one_row_per_team_per_game(rest):
    # 272 games x 2 teams
    assert rest.num_rows == 544


def test_every_team_has_exactly_one_season_opener(con):
    n = con.execute("select count(*) from rest where is_season_opener").fetchone()[0]
    assert n == 32


def test_opener_has_null_rest_not_zero(con):
    """A season opener has no previous game; days_rest must be NULL, not 0.
    Zero would read as a back-to-back and poison every rest split."""
    r = con.execute("""
        select days_rest, is_b2b, is_short_week from rest
        where team = 'NE' and week = 1
    """).fetchone()
    assert r == (None, False, False)


def test_thursday_games_are_short_weeks_except_thursday_to_thursday(con):
    """Thursday games are short weeks -- unless the team played the PREVIOUS
    Thursday too. KC and LA do exactly that after Thanksgiving 2026, getting 7-8
    days rest. Asserting 'all Thursday games are short weeks' is wrong."""
    rows = con.execute("""
        select team, days_rest from rest
        where is_thursday and week > 1 and not is_short_week
        order by team
    """).fetchall()
    assert rows == [("KC", 7), ("LA", 8)]


def test_every_team_has_a_post_bye_game(con):
    """All 32 teams take a bye, so all 32 must show a post-bye game.

    Detecting this by days_rest >= 12 finds only 30: a bye followed by a Thursday
    game gives 11 days. The week gap is the real definition."""
    n = con.execute(
        "select count(distinct team) from rest where is_post_bye").fetchone()[0]
    assert n == 32


def test_post_bye_rest_can_be_much_shorter_than_two_weeks(con):
    """Guards the bug above. A bye into a Thursday game leaves only 10 days rest,
    well under the 12-day threshold that a days-based rule would use."""
    mn = con.execute(
        "select min(days_rest) from rest where is_post_bye").fetchone()[0]
    assert mn == 10


def test_no_nfl_team_plays_twice_inside_four_days(con):
    """A non-zero value means the window bound is off by one: `4 day preceding`
    counts the Sunday game before a Thursday game, giving 33 false positives."""
    mx = con.execute("select max(games_in_last_4) from rest").fetchone()[0]
    assert mx == 0


def test_six_day_window_flags_exactly_the_short_weeks(con):
    """games_in_last_6 SHOULD fire for short weeks -- that is the signal. It must
    fire for precisely the games on 4-5 days rest, and nothing else."""
    mismatched = con.execute("""
        select count(*) from rest
        where (games_in_last_6 > 0) != (days_rest is not null and days_rest <= 5)
    """).fetchone()[0]
    assert mismatched == 0

    n = con.execute(
        "select count(*) from rest where games_in_last_6 > 0").fetchone()[0]
    assert n == 39   # 33 games on 4 days rest + 6 on 5
