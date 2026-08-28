"""Rest and schedule context (Section 5.3).

Everything here derives from the schedule alone -- no external reference data, so it
is verifiable against nflverse and carries no fabrication risk. Travel distance and
timezone shift need stadium coordinates and are handled separately, where the
coordinate source can be cited.

NFL rest states that actually move prop volume:
    short week      Thursday game, <= 5 days rest
    post-bye        >= 12 days rest
    long rest       Monday -> Sunday

NBA back-to-back logic shares this module because the primitive -- days between a
team's consecutive games -- is identical; only the thresholds differ.
"""
from __future__ import annotations

import duckdb
import pyarrow as pa

SHORT_WEEK_MAX_DAYS = 5

# A bye is a STRUCTURAL fact (the team has no game that week), not a rest-day
# threshold. Thresholding days misses a bye followed by a Thursday game, which
# yields only 11 days rest -- that is how 2 of 32 teams went missing in testing.
# Days-based detection is the NBA/no-week fallback only.
POST_BYE_MIN_DAYS_FALLBACK = 12


def build(schedule: pa.Table, season: int | None = None) -> pa.Table:
    """Rest/schedule context, one row per team-game.

    Home and away are unpivoted into a single team column first: rest is a property
    of a team's sequence of games, so the wide schedule format cannot express it.
    """
    con = duckdb.connect()
    con.register("sched", schedule)
    where = f"where season = {int(season)}" if season is not None else ""

    return con.execute(f"""
        with team_games as (
            select game_id, season, week, gameday, weekday, gametime, stadium,
                   home_team as team, away_team as opponent, true as is_home
            from sched {where}
            union all
            select game_id, season, week, gameday, weekday, gametime, stadium,
                   away_team as team, home_team as opponent, false as is_home
            from sched {where}
        ),
        dated as (
            select *, strptime(gameday, '%Y-%m-%d')::date as game_date
            from team_games
        ),
        rested as (
            select *,
                date_diff('day', lag(game_date) over w, game_date) as days_rest,
                week - (lag(week) over w) as week_gap
            from dated
            window w as (partition by team order by game_date)
        )
        select
            game_id, season, week, team, opponent, is_home, stadium,
            game_date, weekday, gametime, days_rest,
            -- NFL
            coalesce(days_rest <= {SHORT_WEEK_MAX_DAYS}, false) as is_short_week,
            coalesce(
                case when week is not null and week_gap is not null
                     then week_gap > 1
                     else days_rest >= {POST_BYE_MIN_DAYS_FALLBACK} end,
                false)                                          as is_post_bye,
            weekday = 'Thursday'                                as is_thursday,
            weekday = 'Monday'                                  as is_monday,
            -- NBA (same primitive, different thresholds)
            coalesce(days_rest = 1, false)                      as is_b2b,
            days_rest is null                                   as is_season_opener,
            -- Density over the DATE axis, not a row offset: row offsets silently
            -- mismeasure when a team has an irregular gap.
            -- "3 games in 4 nights" means 3 games inside a 4-CALENDAR-DAY span, i.e.
            -- today plus the 3 days before it. Using `4 day preceding` counts a game
            -- exactly 4 days back and turns every NFL Sunday->Thursday into a false
            -- positive, so the bound is 3 days, not 4.
            count(*) over (
                partition by team order by game_date
                range between interval 3 day preceding and interval 1 day preceding
            ) as games_in_last_4,
            count(*) over (
                partition by team order by game_date
                range between interval 5 day preceding and interval 1 day preceding
            ) as games_in_last_6
        from rested
        order by team, game_date
    """).to_arrow_table()
