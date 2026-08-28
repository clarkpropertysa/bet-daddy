"""NFL opportunity and usage features (Section 5.1).

Volume predicts props far better than efficiency does, so this is the first feature
family built. Everything is a SHARE of the team's opportunity in that game, not a raw
count: 6 targets means something different on a team that threw 45 times than on one
that threw 22.

Definitions (all standard nflverse/nflfastR derivations):
    target_share      player targets / team targets
    air_yards_share   player air yards / team air yards
    WOPR              1.5 * target_share + 0.7 * air_yards_share
                      (Weighted Opportunity Rating -- the standard receiving
                      opportunity composite; weights are the published ones)
    carry_share       player carries / team carries
    rz_target_share   targets inside the 20 / team targets inside the 20
    rz_carry_share    carries inside the 20 / team carries inside the 20
    snap_pct          from snap_counts (offense_pct), joined separately

air_yards_share can legitimately EXCEED 1.0. Air yards are signed -- screens and
checkdowns behind the line carry negative values -- so a deep threat can hold more
air yards than his team's net total. This is expected in the nflfastR definition and
must not be "fixed" by clamping, which would distort WOPR.

Route participation is NOT here: it needs FTN charting or participation data, which
is a separate release with its own coverage gaps. Adding a fabricated proxy for it
would be worse than leaving it out (Section 0 rule 3).

Plays are filtered to real offensive scrimmage plays: no special teams, no two-point
conversions, and penalties that nullify a play carry no opportunity.
"""
from __future__ import annotations

import duckdb
import pyarrow as pa

# Published WOPR weights.
WOPR_TARGET_W = 1.5
WOPR_AIR_YARDS_W = 0.7

RED_ZONE_YARDLINE = 20

_SCRIMMAGE = """
    play_type in ('pass', 'run')
    and coalesce(two_point_attempt, 0) = 0
    and coalesce(special, 0) = 0
"""


def build_player_game_usage(
    pbp_path: str, season_type: str = "REG"
) -> pa.Table:
    """One row per (player, game) with opportunity shares.

    A player appears if he had ANY target or carry in the game. Players with zero
    opportunity are absent rather than zero-filled -- a zero-target game and a
    did-not-play are different facts and must not be conflated.
    """
    con = duckdb.connect()
    st = f"and season_type = '{season_type}'" if season_type else ""

    return con.execute(f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where {_SCRIMMAGE} {st}
        ),
        -- team denominators, computed once per (game, team)
        team as (
            select game_id, season, week, posteam as team,
                   -- A target requires an intended receiver. Sacks and throwaways
                   -- are pass plays with no receiver_player_id; counting them inflates
                   -- the denominator and makes target_share sum to ~0.88, not 1.0.
                   sum(case when play_type = 'pass' and receiver_player_id is not null
                            then 1 else 0 end)                              as team_targets,
                   sum(case when play_type = 'run'  then 1 else 0 end)      as team_carries,
                   sum(coalesce(air_yards, 0))                              as team_air_yards,
                   sum(case when play_type = 'pass' and receiver_player_id is not null
                             and yardline_100 <= {RED_ZONE_YARDLINE}
                            then 1 else 0 end)                              as team_rz_targets,
                   sum(case when play_type = 'run'
                             and yardline_100 <= {RED_ZONE_YARDLINE}
                            then 1 else 0 end)                              as team_rz_carries
            from plays
            group by 1, 2, 3, 4
        ),
        receiving as (
            select game_id, posteam as team, receiver_player_id as player_id,
                   count(*)                                                 as targets,
                   sum(coalesce(complete_pass, 0))                          as receptions,
                   sum(coalesce(air_yards, 0))                              as air_yards,
                   sum(case when yardline_100 <= {RED_ZONE_YARDLINE}
                            then 1 else 0 end)                              as rz_targets
            from plays
            where play_type = 'pass' and receiver_player_id is not null
            group by 1, 2, 3
        ),
        rushing as (
            select game_id, posteam as team, rusher_player_id as player_id,
                   count(*)                                                 as carries,
                   sum(case when yardline_100 <= {RED_ZONE_YARDLINE}
                            then 1 else 0 end)                              as rz_carries
            from plays
            where play_type = 'run' and rusher_player_id is not null
            group by 1, 2, 3
        ),
        combined as (
            select
                coalesce(r.game_id, u.game_id)     as game_id,
                coalesce(r.team, u.team)           as team,
                coalesce(r.player_id, u.player_id) as player_id,
                coalesce(r.targets, 0)             as targets,
                coalesce(r.receptions, 0)          as receptions,
                coalesce(r.air_yards, 0)           as air_yards,
                coalesce(r.rz_targets, 0)          as rz_targets,
                coalesce(u.carries, 0)             as carries,
                coalesce(u.rz_carries, 0)          as rz_carries
            from receiving r
            full outer join rushing u
              on r.game_id = u.game_id and r.player_id = u.player_id and r.team = u.team
        )
        select
            c.player_id, c.game_id, t.season, t.week, c.team,
            c.targets, c.receptions, c.air_yards, c.carries,
            c.rz_targets, c.rz_carries,
            t.team_targets, t.team_carries, t.team_air_yards,
            -- nullif guards the denominator: a team with zero air yards in a game is
            -- rare but real, and 0/0 must be NULL, not 0.
            c.targets::double / nullif(t.team_targets, 0)        as target_share,
            c.air_yards::double / nullif(t.team_air_yards, 0)    as air_yards_share,
            c.carries::double / nullif(t.team_carries, 0)        as carry_share,
            c.rz_targets::double / nullif(t.team_rz_targets, 0)  as rz_target_share,
            c.rz_carries::double / nullif(t.team_rz_carries, 0)  as rz_carry_share,
            {WOPR_TARGET_W} * (c.targets::double / nullif(t.team_targets, 0))
              + {WOPR_AIR_YARDS_W} * (c.air_yards::double / nullif(t.team_air_yards, 0))
                                                                  as wopr
        from combined c
        join team t on t.game_id = c.game_id and t.team = c.team
        order by t.season, t.week, c.team, target_share desc nulls last
    """).to_arrow_table()


def rolling_usage(usage: pa.Table, windows: tuple[int, ...] = (3, 5)) -> pa.Table:
    """Trailing N-game means and trend per player.

    Section 5.1 asks for rolling values AND trend direction, not just season averages.
    Windows exclude the current game so the feature is usable as a prediction input
    without leaking the outcome it is predicting.
    """
    con = duckdb.connect()
    con.register("usage", usage)

    metrics = ["target_share", "air_yards_share", "carry_share", "wopr"]
    cols = []
    for w in windows:
        for m in metrics:
            cols.append(
                f"avg({m}) over (partition by player_id order by season, week "
                f"rows between {w} preceding and 1 preceding) as {m}_r{w}"
            )
    # trend: most recent 3 vs the 3 before that
    trend = (
        "avg(wopr) over (partition by player_id order by season, week "
        "rows between 3 preceding and 1 preceding) - "
        "avg(wopr) over (partition by player_id order by season, week "
        "rows between 6 preceding and 4 preceding) as wopr_trend"
    )
    return con.execute(f"""
        select *, {', '.join(cols)}, {trend}
        from usage
        order by player_id, season, week
    """).to_arrow_table()
