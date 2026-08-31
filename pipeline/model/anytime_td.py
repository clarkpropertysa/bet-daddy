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

from dataclasses import dataclass, field

import duckdb
import numpy as np

# Scoring zones, by yards from the goal line. Split because they convert at wildly
# different rates and pooling them is what this module used to do:
#
#     zone              touches   TD rate
#     inside the 5        1,240     0.437
#     6 to 20             3,589     0.131
#     outside the 20     25,948     0.013
#
# A goal-line touch scores 3.3x more often than a red-zone touch outside the 5. Pooling
# them understates the goal-line back this module's docstring is about and overstates a
# player whose red-zone work is targets at the 18.
ZONE_BOUNDS = {"gl": (0, 5), "rz": (6, 20), "open": (21, 100)}
ZONES = tuple(ZONE_BOUNDS)

RED_ZONE_YARDLINE = 20
GOAL_LINE_YARDLINE = 5

# Pseudo-count for shrinking a player's own zone rate toward his positional baseline.
#
# SHRUNK, NOT SWITCHED. A hard threshold produced exactly the artefact it was meant to
# avoid: Derrick Henry went 0-for-38 on red-zone touches outside the five, cleared the
# threshold, and was assigned a true conversion rate of 0.000 -- so the model said he
# could never score from there. Every other small-sample estimate in this project is
# shrunk (team volume, team ratings, usage trend); this one was not.
#
# rate = (own_tds + k * baseline) / (own_touches + k). With k = 25 a player needs
# roughly a season of zone work to move halfway off his positional baseline, and
# nobody is ever assigned an impossible zero.
OWN_RATE_PSEUDOCOUNT = 25

# Fallbacks if a (position, zone) cell is too thin to measure. Roughly the league
# aggregates; being approximately right beats refusing to price the zone.
FALLBACK_RATE = {"gl": 0.44, "rz": 0.13, "open": 0.013}


@dataclass(frozen=True)
class ZoneUsage:
    touches_per_game: float
    td_rate: float
    #: Weight the player's own rate carried in the blend, 0 to 1.
    own_weight: float
    touches: int

    @property
    def used_own_rate(self) -> bool:
        """Mostly his own number rather than the positional baseline."""
        return self.own_weight >= 0.5


@dataclass
class TdInputs:
    player_id: str
    position: str | None
    games: int
    zones: dict[str, ZoneUsage] = field(default_factory=dict)

    @property
    def rz_touches_per_game(self) -> float:
        """Red-zone touches, goal line included. Kept for the rationale text."""
        return sum(self.zones[z].touches_per_game for z in ("gl", "rz") if z in self.zones)

    @property
    def used_own_rate(self) -> bool:
        return any(z.used_own_rate for z in self.zones.values())


def build_baselines(pbp_path: str, players_path: str,
                    season_type: str = "REG") -> dict[tuple[str, str], float]:
    """(position, zone) -> TD per touch.

    Keyed by zone as well as position because the two interact: a running back
    converts 0.386 at the goal line and 0.073 in the rest of the red zone, while a
    receiver converts 0.453 and 0.185. One rate per position cannot express that.
    """
    con = duckdb.connect()
    rows = con.execute(f"""
        with t as (
            select coalesce(receiver_player_id, rusher_player_id) as pid,
                   yardline_100, coalesce(touchdown, 0) as td
            from read_parquet('{pbp_path}')
            where season_type = '{season_type}'
              and play_type in ('pass','run')
              and coalesce(two_point_attempt,0) = 0 and coalesce(qb_kneel,0) = 0
              and coalesce(receiver_player_id, rusher_player_id) is not null
              and yardline_100 is not null
        )
        select coalesce(pl.position,'UNK') as pos,
               case when t.yardline_100 <= {GOAL_LINE_YARDLINE} then 'gl'
                    when t.yardline_100 <= {RED_ZONE_YARDLINE}  then 'rz'
                    else 'open' end as zone,
               sum(t.td)::double / count(*) as rate,
               count(*) as n
        from t join read_parquet('{players_path}') pl on pl.gsis_id = t.pid
        group by 1, 2 having count(*) >= 60
    """).fetchall()
    return {(pos, zone): rate for pos, zone, rate, _ in rows}


def load_td_inputs(pbp_path: str, players_path: str, player_id: str,
                   baselines: dict[tuple[str, str], float],
                   season_type: str = "REG") -> TdInputs:
    con = duckdb.connect()
    rows = con.execute(f"""
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
              and yardline_100 is not null
        )
        select case when yardline_100 <= {GOAL_LINE_YARDLINE} then 'gl'
                    when yardline_100 <= {RED_ZONE_YARDLINE}  then 'rz'
                    else 'open' end as zone,
               count(*) as touches, sum(td) as tds
        from mine group by 1
    """, [player_id]).fetchall()

    games = con.execute("""
        select count(distinct game_id) from read_parquet(?)
        where season_type = ? and play_type in ('pass','run')
          and coalesce(receiver_player_id, rusher_player_id) = ?
    """, [pbp_path, season_type, player_id]).fetchone()[0] or 0

    pos_row = con.execute(
        f"select position from read_parquet('{players_path}') where gsis_id = ?",
        [player_id]).fetchone()
    position = pos_row[0] if pos_row else None

    by_zone = {z: (0, 0) for z in ZONES}
    for zone, touches, tds in rows:
        by_zone[zone] = (int(touches or 0), int(tds or 0))

    zones: dict[str, ZoneUsage] = {}
    for zone in ZONES:
        touches, tds = by_zone[zone]
        baseline = baselines.get((position or "UNK", zone), FALLBACK_RATE[zone])
        k = OWN_RATE_PSEUDOCOUNT
        rate = (tds + k * baseline) / (touches + k)
        zones[zone] = ZoneUsage(
            touches_per_game=(touches / games) if games else 0.0,
            td_rate=float(rate),
            own_weight=touches / (touches + k),
            touches=touches,
        )

    return TdInputs(player_id=player_id, position=position, games=int(games), zones=zones)


def project_anytime_td(
    inp: TdInputs, adjustments_multiplier: float = 1.0,
    iterations: int = 20_000, seed: int | None = None,
) -> dict:
    """P(at least one touchdown), summed over three scoring zones.

    Modelling the zones separately is the whole point. Pooling them into a single
    red-zone rate did two things wrong: it flattened the 3.3x gap between a goal-line
    carry and a red-zone target, and it ignored the open field entirely -- where 25%
    of all offensive touchdowns are actually scored.
    """
    rng = np.random.default_rng(seed)
    total = np.zeros(iterations, dtype=int)
    detail: dict[str, dict] = {}

    for zone in ZONES:
        z = inp.zones.get(zone)
        if z is None:
            continue
        # Volume adjustments scale opportunity, not conversion.
        mean_touches = max(z.touches_per_game * adjustments_multiplier, 0.0)
        if mean_touches <= 0:
            detail[zone] = {"touches": 0.0, "rate": z.td_rate, "own": z.used_own_rate,
                            "own_weight": round(float(z.own_weight), 3),
                            "zone_touches": z.touches}
            continue
        touches = rng.poisson(mean_touches, size=iterations)
        total += rng.binomial(touches, float(np.clip(z.td_rate, 0.0, 1.0)))
        detail[zone] = {
            "touches": round(float(mean_touches), 3),
            "rate": round(float(z.td_rate), 4),
            "own": z.used_own_rate,
            # The actual blend weight, so the explanation can describe the shrinkage
            # rather than pretending the rate is purely one source or the other.
            "own_weight": round(float(z.own_weight), 3),
            "zone_touches": z.touches,
        }

    p = float((total >= 1).mean())
    return {
        "p_td": p,
        "mean_rz_touches": float(inp.rz_touches_per_game * adjustments_multiplier),
        "td_per_touch": inp.zones["gl"].td_rate if "gl" in inp.zones else 0.0,
        "used_own_rate": inp.used_own_rate,
        "by_zone": detail,
        "iterations": iterations,
    }
