"""With/without teammate splits (Section 5.2).

The build spec calls this the single most exploitable signal in props: when a
teammate is out, usage redistributes unevenly and markets are slow to price the
second-order beneficiaries.

It is also where this kind of tool most often lies to itself. Most with/without
splits are noise. A receiver's target share over 3 games without his WR1 is a number
with an enormous standard error, and presenting it as "his share jumps to 28%" is how
a research tool manufactures confident losing bets.

So every split here carries:
    n_with, n_without       sample sizes, always rendered
    delta                   without - with
    ci_low, ci_high         95% Welch CI on the delta
    significant             whether the CI excludes zero
    suppressed              whether it fails the sample-size floor
    confound_regulars_out   mean number of regulars absent in the "without" games

KNOWN LIMITATION -- pairwise splits are confounded. When several players are out in
the same games, each pairwise split attributes the whole effect to its own teammate.
Restricting teammates to skill positions removes the worst of it (offensive tackles
were driving two of the five largest 2025 splits), but simultaneous skill-position
absences still confound. `confound_regulars_out` exposes this per row so the UI can
label it; proper attribution needs a multivariate model and is deliberately not
claimed here.

Availability comes from SNAP COUNTS, not from whether the player recorded a target.
A receiver who played 40 snaps and drew zero targets is present, not absent; treating
him as absent would fabricate the exact effect we are trying to measure.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pyarrow as pa
from scipy import stats

# Sample-size floor. Deliberately low as a hard gate -- the confidence interval does
# the real work. A split that passes this but has a CI spanning zero is still noise,
# and the UI must show it as such rather than hiding it.
MIN_GAMES_WITH = 4
MIN_GAMES_WITHOUT = 4

# A teammate only matters if he is normally a real part of the offense.
MIN_TEAMMATE_SNAP_PCT = 0.35
MIN_TEAMMATE_GAMES = 4

# Only positions with a coherent mechanism for redistributing TARGETS and CARRIES.
# Without this filter the top "signals" are driven by offensive tackles: an OT's
# absence cannot free up targets, it merely co-occurs with other injuries. Two of
# the five largest 2025 splits were OT-driven before this gate existed.
SKILL_POSITIONS = ("QB", "RB", "FB", "WR", "TE")


def build_availability(
    snap_counts_path: str, players_path: str
) -> pa.Table:
    """(player, game) rows for everyone who took an offensive snap.

    snap_counts keys on pfr_player_id; everything else keys on gsis_id. The players
    release maps between them at 99.7% coverage (weekly rosters manage only 65.9%).
    """
    con = duckdb.connect()
    return con.execute(f"""
        with idmap as (
            select distinct pfr_id, gsis_id
            from read_parquet('{players_path}')
            where pfr_id is not null and gsis_id is not null
        )
        select
            m.gsis_id as player_id, s.game_id, s.season, s.week, s.team,
            s.offense_snaps, s.offense_pct
        from read_parquet('{snap_counts_path}') s
        join idmap m on m.pfr_id = s.pfr_player_id
        where s.offense_snaps > 0
    """).to_arrow_table()


def build_with_without(
    usage: pa.Table,
    availability: pa.Table,
    players: pa.Table,
    metric: str = "target_share",
    min_games_with: int = MIN_GAMES_WITH,
    min_games_without: int = MIN_GAMES_WITHOUT,
) -> pa.Table:
    """For each (player, teammate) pair, the player's metric with vs without him.

    Returns one row per pair with sample sizes and a Welch confidence interval on
    the difference. Nothing is filtered out: rows that fail the floor are returned
    with suppressed=true so the caller can show them as unvalidated rather than
    silently dropping evidence.
    """
    if metric not in usage.column_names:
        raise ValueError(f"unknown metric {metric!r}")

    con = duckdb.connect()
    con.register("usage", usage)
    con.register("avail", availability)
    con.register("players", players)

    pos_list = ", ".join(f"'{p}'" for p in SKILL_POSITIONS)
    agg = con.execute(f"""
        with
        -- teammates who are actually part of the offense, not fringe roster bodies,
        -- and whose absence has a mechanism to move targets or carries
        regulars as (
            select a.player_id, a.team, count(*) as g
            from avail a
            join players p on p.gsis_id = a.player_id
            where a.offense_pct >= {MIN_TEAMMATE_SNAP_PCT}
              and p.position in ({pos_list})
            group by 1, 2
            having count(*) >= {MIN_TEAMMATE_GAMES}
        ),
        -- every game each team played, so "absent" can be distinguished from
        -- "team had no game". Without this, a bye week reads as an injury.
        team_games as (
            select distinct team, game_id, season, week from avail
        ),
        -- did the regular play in that team-game?
        presence as (
            select r.player_id as mate_id, tg.team, tg.game_id,
                   (a.player_id is not null) as mate_played
            from regulars r
            join team_games tg on tg.team = r.team
            left join avail a
              on a.player_id = r.player_id and a.game_id = tg.game_id
        ),
        -- focal player's metric in games he himself played
        focal as (
            select u.player_id, u.team, u.game_id, u.{metric} as val
            from usage u
            join avail a on a.player_id = u.player_id and a.game_id = u.game_id
            where u.{metric} is not null
        ),
        -- how many regulars were absent in each team-game. This is the confounding
        -- measure: if the games without teammate T are also the games without four
        -- other starters, the split cannot attribute the effect to T.
        absences as (
            select team, game_id, sum(case when not mate_played then 1 else 0 end) as n_out
            from presence
            group by 1, 2
        )
        select
            f.player_id, p.mate_id, f.team,
            p.mate_played,
            count(*)           as n,
            avg(f.val)         as mean_val,
            stddev_samp(f.val) as sd_val,
            avg(ab.n_out)      as mean_regulars_out
        from focal f
        join presence p on p.game_id = f.game_id and p.team = f.team
        join absences ab on ab.game_id = f.game_id and ab.team = f.team
        where p.mate_id != f.player_id
        group by 1, 2, 3, 4
    """).to_arrow_table().to_pylist()

    # pivot with/without into one row per pair
    pairs: dict[tuple, dict] = {}
    for r in agg:
        key = (r["player_id"], r["mate_id"], r["team"])
        d = pairs.setdefault(key, {})
        d["with" if r["mate_played"] else "without"] = r

    rows = []
    for (pid, mid, team), d in pairs.items():
        w, wo = d.get("with"), d.get("without")
        n_w = w["n"] if w else 0
        n_wo = wo["n"] if wo else 0

        delta = ci_lo = ci_hi = None
        significant = False
        if w and wo and n_w > 1 and n_wo > 1:
            m_w, m_wo = w["mean_val"], wo["mean_val"]
            s_w = w["sd_val"] or 0.0
            s_wo = wo["sd_val"] or 0.0
            delta = m_wo - m_w
            se = float(np.sqrt(s_w**2 / n_w + s_wo**2 / n_wo))
            if se > 0:
                # Welch-Satterthwaite: unequal variances and unequal n are the norm
                # here, so a pooled-variance t would understate the interval.
                df_num = (s_w**2 / n_w + s_wo**2 / n_wo) ** 2
                df_den = ((s_w**2 / n_w) ** 2 / (n_w - 1)
                          + (s_wo**2 / n_wo) ** 2 / (n_wo - 1))
                df = df_num / df_den if df_den > 0 else 1.0
                tcrit = float(stats.t.ppf(0.975, df))
                ci_lo, ci_hi = delta - tcrit * se, delta + tcrit * se
                significant = (ci_lo > 0) or (ci_hi < 0)

        rows.append({
            "player_id": pid,
            "teammate_id": mid,
            "team": team,
            "metric": metric,
            "n_with": n_w,
            "n_without": n_wo,
            "mean_with": w["mean_val"] if w else None,
            "mean_without": wo["mean_val"] if wo else None,
            "delta": delta,
            "ci_low": ci_lo,
            "ci_high": ci_hi,
            "significant": bool(significant),
            "suppressed": n_w < min_games_with or n_wo < min_games_without,
            # >1 means other regulars were typically out in the same games, so the
            # effect cannot be attributed to this teammate alone.
            "confound_regulars_out": (wo["mean_regulars_out"] if wo else None),
        })

    return pa.Table.from_pylist(rows, schema=pa.schema([
        ("player_id", pa.string()), ("teammate_id", pa.string()),
        ("team", pa.string()), ("metric", pa.string()),
        ("n_with", pa.int64()), ("n_without", pa.int64()),
        ("mean_with", pa.float64()), ("mean_without", pa.float64()),
        ("delta", pa.float64()), ("ci_low", pa.float64()),
        ("ci_high", pa.float64()), ("significant", pa.bool_()),
        ("suppressed", pa.bool_()), ("confound_regulars_out", pa.float64()),
    ]))
