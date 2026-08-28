"""Opponent defense grades (Section 5.4).

INFERRED, NOT CHARTED. True shadow-coverage data is not free. These grades come from
play-by-play outcomes: what a defense actually allowed, split by target depth band and
by receiver position. They do not know who covered whom. The UI must label them as
inferred -- claiming charted coverage we do not have would be a lie about provenance.

Depth bands follow the standard nflfastR convention on air yards:
    short         < 10 air yards
    intermediate  10-19
    deep          >= 20

Grades are per (defense, split) and carry BOTH the raw rate and a rank among the 32
teams, because a rank is what a human reads and a rate is what a model multiplies.

EPA per target is the primary metric rather than yards allowed: yards allowed is
heavily confounded by volume, and a defense that faces 40 targets a game will look
worse than one that faces 25 regardless of quality.
"""
from __future__ import annotations

import duckdb
import pyarrow as pa

SHORT_MAX = 10
INTERMEDIATE_MAX = 20

# Below this a split is too thin to rank; the grade is emitted with a null rank so
# the caller can render "insufficient sample" rather than a misleading number.
MIN_TARGETS_FOR_RANK = 25
MIN_CARRIES_FOR_RANK = 25

_DEPTH_BAND = f"""
    case
        when air_yards < {SHORT_MAX} then 'short'
        when air_yards < {INTERMEDIATE_MAX} then 'intermediate'
        else 'deep'
    end
"""


def build_pass_defense_grades(
    pbp_path: str, players_path: str, season_type: str = "REG"
) -> pa.Table:
    """Pass defense allowed, split by target depth band and receiver position."""
    con = duckdb.connect()
    st = f"and season_type = '{season_type}'" if season_type else ""

    return con.execute(f"""
        with targets as (
            select
                p.defteam as team, p.season,
                {_DEPTH_BAND} as depth_band,
                coalesce(pl.position, 'UNK') as receiver_position,
                p.epa,
                coalesce(p.complete_pass, 0) as completed,
                coalesce(p.yards_gained, 0)  as yards,
                -- nflfastR success: EPA > 0 on the play
                case when p.epa > 0 then 1 else 0 end as success
            from read_parquet('{pbp_path}') p
            left join read_parquet('{players_path}') pl
                   on pl.gsis_id = p.receiver_player_id
            where p.play_type = 'pass'
              and p.receiver_player_id is not null
              and p.air_yards is not null
              and coalesce(p.two_point_attempt, 0) = 0
              {st}
        ),
        agg as (
            select team, season, depth_band, receiver_position,
                   count(*)          as targets,
                   sum(completed)    as completions,
                   sum(yards)        as yards_allowed,
                   avg(epa)          as epa_per_target,
                   avg(success)      as success_rate_allowed,
                   avg(yards)        as yards_per_target
            from targets
            group by 1, 2, 3, 4
        )
        select *,
            -- rank 1 = BEST defense (lowest EPA allowed). Suppressed to null on a
            -- thin sample so the UI cannot render a confident rank off 6 targets.
            case when targets >= {MIN_TARGETS_FOR_RANK} then
                rank() over (
                    partition by season, depth_band, receiver_position
                    order by epa_per_target
                )
            end as epa_rank,
            targets >= {MIN_TARGETS_FOR_RANK} as rankable,
            'inferred_from_pbp' as provenance
        from agg
        order by season, depth_band, receiver_position, epa_per_target
    """).to_arrow_table()


def build_rush_defense_grades(
    pbp_path: str, season_type: str = "REG"
) -> pa.Table:
    """Run defense allowed, by run location plus an overall team row.

    Plays with a NULL run_location are excluded from the gap splits. There are 128
    of them in 2025 (0.9% of runs) averaging -1.63 EPA -- botched snaps and aborted
    plays, not a gap. Bucketing them as 'unknown' produced a fake elite grade for
    every defense that happened to face more of them.

    They are still counted in the 'all' row, because they did happen.
    """
    con = duckdb.connect()
    st = f"and season_type = '{season_type}'" if season_type else ""

    return con.execute(f"""
        with carries as (
            select
                defteam as team, season, run_location,
                epa,
                coalesce(yards_gained, 0) as yards,
                case when epa > 0 then 1 else 0 end as success
            from read_parquet('{pbp_path}')
            where play_type = 'run'
              and rusher_player_id is not null
              and coalesce(two_point_attempt, 0) = 0
              and coalesce(qb_kneel, 0) = 0
              {st}
        ),
        agg as (
            select team, season, run_location,
                   count(*)     as carries,
                   sum(yards)   as yards_allowed,
                   avg(epa)     as epa_per_carry,
                   avg(success) as success_rate_allowed,
                   avg(yards)   as yards_per_carry
            from carries
            where run_location is not null
            group by 1, 2, 3
            union all
            -- team-level row keeps every carry, including the unlocated ones
            select team, season, 'all' as run_location,
                   count(*), sum(yards), avg(epa), avg(success), avg(yards)
            from carries
            group by 1, 2
        )
        select *,
            case when carries >= {MIN_CARRIES_FOR_RANK} then
                rank() over (partition by season, run_location order by epa_per_carry)
            end as epa_rank,
            carries >= {MIN_CARRIES_FOR_RANK} as rankable,
            'inferred_from_pbp' as provenance
        from agg
        order by season, run_location, epa_per_carry
    """).to_arrow_table()
