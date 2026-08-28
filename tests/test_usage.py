"""NFL usage features, cross-validated against nflverse's own weekly stats.

Deriving targets/carries from play-by-play and then checking them against the
official weekly stat lines is the strongest integrity test available here: two
independent nflverse products have to agree.
"""
import duckdb
import pytest

from pipeline.features.usage import build_player_game_usage
from pipeline.ingest.nflverse import fetch

pytestmark = pytest.mark.network

PBP_2025 = "data/raw/nflverse/pbp_2025.parquet"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.register("usage", build_player_game_usage(PBP_2025))
    c.register("weekly", fetch("player_stats_week", 2025))
    return c


def test_target_shares_sum_to_one_per_team_game(con):
    """The denominator must count only pass plays with an intended receiver.
    Including sacks and throwaways makes these sum to ~0.88."""
    worst = con.execute("""
        select max(abs(s - 1.0)) from (
            select game_id, team, sum(target_share) s
            from usage where target_share is not null
            group by 1, 2
        )
    """).fetchone()[0]
    assert worst < 1e-9


def test_carry_shares_sum_to_one_per_team_game(con):
    worst = con.execute("""
        select max(abs(s - 1.0)) from (
            select game_id, team, sum(carry_share) s
            from usage where carry_share is not null
            group by 1, 2
        )
    """).fetchone()[0]
    assert worst < 1e-9


def test_pbp_targets_match_official_weekly_stats(con):
    """Targets derived from pbp must equal nflverse's own weekly target counts."""
    mismatches = con.execute("""
        select count(*) from usage u
        join weekly w
          on w.player_id = u.player_id and w.season = u.season and w.week = u.week
         and w.season_type = 'REG'
        where u.targets != coalesce(w.targets, 0)
    """).fetchone()[0]
    assert mismatches == 0


def test_pbp_receptions_match_official_weekly_stats(con):
    mismatches = con.execute("""
        select count(*) from usage u
        join weekly w
          on w.player_id = u.player_id and w.season = u.season and w.week = u.week
         and w.season_type = 'REG'
        where u.receptions != coalesce(w.receptions, 0)
    """).fetchone()[0]
    assert mismatches == 0


def test_air_yards_share_may_exceed_one(con):
    """Air yards are signed: screens carry negative values, so a deep threat can
    hold more air yards than his team's net total. Clamping this would distort WOPR,
    so the pipeline must tolerate it -- this test pins that as intended behaviour."""
    n = con.execute(
        "select count(*) from usage where air_yards_share > 1.0").fetchone()[0]
    assert n > 0


def test_no_share_exceeds_one_for_countable_denominators(con):
    """Targets and carries are counts, never negative, so their shares are bounded."""
    n = con.execute("""
        select count(*) from usage
        where target_share > 1.0000001 or carry_share > 1.0000001
           or rz_target_share > 1.0000001 or rz_carry_share > 1.0000001
    """).fetchone()[0]
    assert n == 0


def test_zero_opportunity_players_are_absent_not_zero_filled(con):
    """A zero-target game and a did-not-play are different facts. Every row must
    carry at least one target or carry."""
    n = con.execute(
        "select count(*) from usage where targets = 0 and carries = 0").fetchone()[0]
    assert n == 0
