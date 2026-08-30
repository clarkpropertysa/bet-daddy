"""Anytime touchdown probability.

A different problem from a yardage total: this is P(at least one TD), which is driven
by GOAL-LINE and RED-ZONE opportunity rather than volume. A back with 4 carries inside
the 5 is a better anytime-TD bet than one with 20 carries between the 20s.

Structure:
  1. Expected red-zone touches (carries + targets inside the 20), from the player's
     own share of his team's red-zone work.
  2. Per-touch TD conversion, from the player's own history where it exists and his
     positional baseline where it does not -- a receiver with 6 red-zone targets has
     no reliable personal rate.
  3. P(>=1 TD) = 1 - (1-p)^touches, simulated so the touch count carries its own
     variance rather than being fixed at its mean.

Positional baselines are MEASURED from play-by-play, not assumed.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

RED_ZONE_YARDLINE = 20
GOAL_LINE_YARDLINE = 5

# Below this a player's own conversion rate is noise and the positional baseline is
# used instead.
MIN_TOUCHES_FOR_OWN_RATE = 25


@dataclass
class TdInputs:
    player_id: str
    position: str | None
    games: int
    rz_touches_per_game: float
    gl_touches_per_game: float
    td_per_rz_touch: float
    used_own_rate: bool
    baseline_rate: float


def build_baselines(pbp_path: str, players_path: str,
                    season_type: str = "REG") -> dict[str, float]:
    con = duckdb.connect()
    rows = con.execute(f"""
        with rz as (
            select coalesce(receiver_player_id, rusher_player_id) as pid,
                   coalesce(touchdown, 0) as td
            from read_parquet('{pbp_path}')
            where season_type = '{season_type}'
              and yardline_100 <= {RED_ZONE_YARDLINE}
              and play_type in ('pass','run')
              and coalesce(two_point_attempt,0) = 0 and coalesce(qb_kneel,0) = 0
              and coalesce(receiver_player_id, rusher_player_id) is not null
        )
        select coalesce(pl.position,'UNK') as pos,
               sum(rz.td)::double / count(*) as rate, count(*) as n
        from rz join read_parquet('{players_path}') pl on pl.gsis_id = rz.pid
        group by 1 having count(*) >= 100
    """).fetchall()
    return {pos: rate for pos, rate, _ in rows}


def load_td_inputs(pbp_path: str, players_path: str, player_id: str,
                   baselines: dict[str, float], season_type: str = "REG") -> TdInputs:
    con = duckdb.connect()
    row = con.execute(f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where season_type = '{season_type}'
              and coalesce(two_point_attempt,0)=0 and coalesce(qb_kneel,0)=0
              and play_type in ('pass','run')
        ),
        mine as (
            select game_id, yardline_100, coalesce(touchdown,0) td
            from plays
            where coalesce(receiver_player_id, rusher_player_id) = ?
        )
        select
            (select count(distinct game_id) from plays
              where coalesce(receiver_player_id, rusher_player_id) = ?),
            (select count(*) from mine where yardline_100 <= {RED_ZONE_YARDLINE}),
            (select count(*) from mine where yardline_100 <= {GOAL_LINE_YARDLINE}),
            (select sum(td) from mine where yardline_100 <= {RED_ZONE_YARDLINE})
    """, [player_id, player_id]).fetchone()

    games, rz_touches, gl_touches, rz_tds = [x or 0 for x in row]
    pos = con.execute(
        f"select position from read_parquet('{players_path}') where gsis_id = ?",
        [player_id]).fetchone()
    position = pos[0] if pos else None
    baseline = baselines.get(position or "UNK", 0.08)

    use_own = rz_touches >= MIN_TOUCHES_FOR_OWN_RATE
    rate = (rz_tds / rz_touches) if use_own and rz_touches else baseline

    return TdInputs(
        player_id=player_id, position=position, games=int(games),
        rz_touches_per_game=(rz_touches / games) if games else 0.0,
        gl_touches_per_game=(gl_touches / games) if games else 0.0,
        td_per_rz_touch=float(rate), used_own_rate=bool(use_own),
        baseline_rate=float(baseline),
    )


def project_anytime_td(
    inp: TdInputs, adjustments_multiplier: float = 1.0,
    iterations: int = 20_000, seed: int | None = None,
) -> dict:
    """P(at least one touchdown)."""
    rng = np.random.default_rng(seed)
    mean_touches = max(inp.rz_touches_per_game * adjustments_multiplier, 0.0)
    if mean_touches <= 0:
        return {"p_td": 0.0, "mean_rz_touches": 0.0,
                "td_per_touch": inp.td_per_rz_touch, "iterations": iterations}

    # Poisson touches, then a binomial TD on each. Simulating the touch count keeps
    # its variance in the answer rather than collapsing to the mean.
    touches = rng.poisson(mean_touches, size=iterations)
    tds = rng.binomial(touches, np.clip(inp.td_per_rz_touch, 0.0, 1.0))
    p = float((tds >= 1).mean())
    return {
        "p_td": p,
        "mean_rz_touches": float(touches.mean()),
        "td_per_touch": inp.td_per_rz_touch,
        "used_own_rate": inp.used_own_rate,
        "iterations": iterations,
    }
