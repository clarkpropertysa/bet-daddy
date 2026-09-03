"""Team play volume, so player props can be modelled as share x opportunity.

WHY THIS EXISTS. Projecting a player's targets from his own historical target count
conflates two different things: how much his team throws, and how much of that he
commands. They move independently — a team can change coordinators and throw ten more
times a game while a receiver's role is unchanged, or a teammate can get hurt and the
share move while team volume does not. Splitting them lets `features/usage.py` supply
the share and `features/splits.py` adjust it, which is what those modules were built
for.

    player_targets = team_pass_attempts x player_target_share

MEASURED, NOT ASSUMED. Year-over-year stability across 96 team-seasons:

    plays per game   r = 0.144,  r^2 = 0.021,  optimal shrinkage 0.14
    pass attempts    r = 0.377,  r^2 = 0.142,  optimal shrinkage 0.33
    pass RATE        r = 0.446,  r^2 = 0.199,  optimal shrinkage 0.39

Team play count is almost entirely unpredictable from the prior season — 2% of
variance — so it is shrunk nearly to the league mean and a team's own pace is worth
very little until the current season provides some. Pass rate is the most stable team
trait and survives at 0.39.

A NEGATIVE RESULT WORTH RECORDING: the projected game total does NOT predict play
count (r = 0.030 over 1,632 team-games). Section 5.5 treats the total as a primary
driver of prop volume; for the number of snaps a team runs, it is not one. High totals
come from efficiency, not from more plays. The total is therefore deliberately absent
from this model.

The SPREAD does move the pass/run split, in the expected direction and modestly:

    pass_rate = 0.5735 - 0.00316 * team_spread      r = -0.188

A seven-point underdog throws about 2.2 percentage points more often than a pick'em.
Real, and small.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pyarrow as pa

# Measured over 96 team-seasons; see module docstring.
PLAYS_SHRINKAGE = 0.14
PASS_RATE_SHRINKAGE = 0.39
#: Targets per pass PLAY. Year-over-year r = 0.502 (r^2 = 0.252) over 96
#: team-seasons -- the most stable of the three, since it is mostly a team's sack and
#: scramble rate.
TARGET_RATIO_SHRINKAGE = 0.50

# pass_rate = intercept + slope * team_spread (positive spread = favoured)
SPREAD_PASS_RATE_SLOPE = -0.00316

# Games of current-season data at which it fully replaces the prior-season prior.
FULL_WEIGHT_GAMES = 6

LEAGUE_PLAYS_PER_GAME = 61.3
LEAGUE_PASS_RATE = 0.574
#: 0.8950 / 0.8892 / 0.8932 / 0.8904 across 2022-25 -- flat enough to be a constant.
LEAGUE_TARGET_RATIO = 0.891


@dataclass(frozen=True)
class TeamVolume:
    team: str
    plays: float
    pass_attempts: float
    rush_attempts: float
    pass_rate: float
    games_current: int
    prior_only: bool
    #: Targets per pass play. Sacks and throwaways are pass plays with no receiver.
    target_ratio: float = LEAGUE_TARGET_RATIO

    @property
    def targets(self) -> float:
        """Team TARGETS -- the denominator `usage.py` divides by for target_share.

        NOT `pass_attempts`. A share whose denominator excludes sacks and throwaways
        must be multiplied by a volume that also excludes them; pairing it with pass
        PLAYS inflates every receiving projection by about 11%, always upward. This
        is the exact error `usage.py:68-71` warns about, made one module over.

        Derived from `pass_attempts` rather than stored, so the spread adjustment in
        `project_for_game` flows through to targets automatically.
        """
        return self.pass_attempts * self.target_ratio


def _team_query(pbp_path: str, season_type: str) -> str:
    """Per-team pace, pass rate, and the share of pass plays that are TARGETS.

    The scrimmage filter must match `features/usage.py:_SCRIMMAGE` exactly. The two
    modules divide the same plays -- usage.py supplies the numerator (a player's
    share), this module the denominator (team volume) -- and any play counted by one
    and not the other biases their product. They disagreed on `special` and
    `qb_kneel`, so `carry_share`'s denominator included kneels while the rush
    attempts it multiplied did not.
    """
    return f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where season_type = '{season_type}'
              and play_type in ('pass','run')
              and coalesce(two_point_attempt,0) = 0
              and coalesce(qb_kneel,0) = 0
              and coalesce(special,0) = 0
        )
        select posteam team,
               count(distinct game_id) g,
               count(*)::double / count(distinct game_id) plays_pg,
               avg(case when play_type='pass' then 1.0 else 0.0 end) pass_rate,
               -- Of the pass PLAYS, the fraction that produced a target. Sacks and
               -- throwaways have no receiver, so they are pass plays that no player
               -- can hold a share of. See TARGET_RATIO below.
               sum(case when play_type='pass' and receiver_player_id is not null
                        then 1.0 else 0.0 end)
                 / nullif(sum(case when play_type='pass' then 1.0 else 0.0 end), 0)
                                                          as target_ratio
        from plays group by 1
    """


def build_team_volume(
    prior_pbp_path: str,
    current_pbp_path: str | None = None,
    season_type: str = "REG",
) -> pa.Table:
    """Blended per-team pace and pass rate, before game-specific adjustment."""
    con = duckdb.connect()
    con.execute(f"create or replace view prior as {_team_query(prior_pbp_path, season_type)}")
    if current_pbp_path:
        con.execute(f"create or replace view cur as {_team_query(current_pbp_path, season_type)}")
    else:
        con.execute("create or replace view cur as select * from prior where false")

    return con.execute(f"""
        with blended as (
            select p.team,
                   coalesce(c.g, 0) as games_current,
                   least(coalesce(c.g,0)::double / {FULL_WEIGHT_GAMES}, 1.0) as w,
                   p.plays_pg     as prior_plays,
                   p.pass_rate    as prior_rate,
                   p.target_ratio as prior_tratio,
                   c.plays_pg     as cur_plays,
                   c.pass_rate    as cur_rate,
                   c.target_ratio as cur_tratio
            from prior p left join cur c on c.team = p.team
        )
        select team, games_current,
               -- prior season is shrunk toward the league mean; current season is not
               (1 - w) * ({LEAGUE_PLAYS_PER_GAME}
                          + (prior_plays - {LEAGUE_PLAYS_PER_GAME}) * {PLAYS_SHRINKAGE})
                 + w * coalesce(cur_plays, {LEAGUE_PLAYS_PER_GAME})      as plays,
               (1 - w) * ({LEAGUE_PASS_RATE}
                          + (prior_rate - {LEAGUE_PASS_RATE}) * {PASS_RATE_SHRINKAGE})
                 + w * coalesce(cur_rate, {LEAGUE_PASS_RATE})            as pass_rate,
               (1 - w) * ({LEAGUE_TARGET_RATIO}
                          + (coalesce(prior_tratio, {LEAGUE_TARGET_RATIO})
                             - {LEAGUE_TARGET_RATIO}) * {TARGET_RATIO_SHRINKAGE})
                 + w * coalesce(cur_tratio, {LEAGUE_TARGET_RATIO})       as target_ratio
        from blended order by team
    """).to_arrow_table()


def volume_dict(tbl: pa.Table) -> dict[str, TeamVolume]:
    out: dict[str, TeamVolume] = {}
    for r in tbl.to_pylist():
        plays, rate = float(r["plays"]), float(r["pass_rate"])
        tratio = float(r["target_ratio"] or LEAGUE_TARGET_RATIO)
        out[r["team"]] = TeamVolume(
            team=r["team"], plays=plays,
            pass_attempts=plays * rate, rush_attempts=plays * (1 - rate),
            pass_rate=rate, games_current=int(r["games_current"]),
            prior_only=int(r["games_current"]) == 0,
            target_ratio=tratio,
        )
    return out


def project_for_game(
    tv: TeamVolume, team_spread: float | None = None,
) -> TeamVolume:
    """Apply game script. Positive `team_spread` means this team is favoured.

    Only the pass/run SPLIT moves — total plays are left alone, because the game
    total does not predict play count and the spread's effect on pace is not
    separable from noise at this sample size.
    """
    if team_spread is None:
        return tv
    rate = tv.pass_rate + SPREAD_PASS_RATE_SLOPE * team_spread
    rate = max(0.30, min(0.80, rate))   # keep inside anything ever observed
    return TeamVolume(
        team=tv.team, plays=tv.plays,
        pass_attempts=tv.plays * rate, rush_attempts=tv.plays * (1 - rate),
        pass_rate=rate, games_current=tv.games_current, prior_only=tv.prior_only,
        target_ratio=tv.target_ratio,
    )
