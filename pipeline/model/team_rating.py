"""Team strength from EPA, and a projected game margin.

Ratings are net EPA per play: a team's offensive EPA/play minus the EPA/play its
defense allows. The conversion to points is FITTED, not assumed — least squares of
actual margin on rating differential across a full season.

2025 fit (272 regular-season games):
    42.1 points per net EPA/play
    +2.12 points home-field advantage   (consistent with the modern ~2-2.5 estimate)
    R^2 0.318, RMSE 11.68 points

READ THAT RMSE BEFORE TRUSTING A LEAN. An 11.7-point standard error means a
single-game margin projection is weak — most NFL games are decided inside the noise.
The number worth looking at is not the projected margin but its DISAGREEMENT with the
market, and even that is a soft signal on one game.

Ratings for a season are built from the PRIOR season, so projecting 2026 from 2025 is
genuinely out of sample. The fit constants above were estimated in-sample on 2025 and
are treated as priors, not as evidence of accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pyarrow as pa

POINTS_PER_NET_EPA = 42.12
HOME_FIELD_ADVANTAGE = 2.12

# Below this the lean is inside the model's own noise and is not worth showing as a
# disagreement. Deliberately wide: RMSE is 11.7 points.
MIN_MEANINGFUL_EDGE_PTS = 1.5


@dataclass(frozen=True)
class TeamRating:
    team: str
    off_epa: float
    def_epa: float
    net: float
    off_rank: int
    def_rank: int


def build_ratings(pbp_path: str, season_type: str = "REG") -> pa.Table:
    con = duckdb.connect()
    return con.execute(f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where season_type = '{season_type}' and epa is not null
              and play_type in ('pass','run') and coalesce(qb_kneel,0) = 0
        ),
        off as (select posteam team, avg(epa) off_epa, count(*) plays from plays group by 1),
        def as (select defteam team, avg(epa) def_epa from plays group by 1)
        select o.team, o.off_epa, d.def_epa,
               o.off_epa - d.def_epa as net, o.plays,
               rank() over (order by o.off_epa desc) as off_rank,
               rank() over (order by d.def_epa asc)  as def_rank
        from off o join def d on d.team = o.team
        order by net desc
    """).to_arrow_table()


@dataclass(frozen=True)
class GameLean:
    home: str
    away: str
    projected_margin: float      # positive = home favoured
    market_spread: float | None  # nflverse convention: positive = home favoured
    disagreement: float | None
    favoured: str
    confident: bool
    why: list[str]


def project_game(
    home: str, away: str, ratings: dict[str, TeamRating],
    market_spread: float | None = None, neutral_site: bool = False,
) -> GameLean | None:
    h, a = ratings.get(home), ratings.get(away)
    if not h or not a:
        return None

    hfa = 0.0 if neutral_site else HOME_FIELD_ADVANTAGE
    margin = (h.net - a.net) * POINTS_PER_NET_EPA + hfa
    favoured = home if margin >= 0 else away

    why: list[str] = []
    off_gap = h.off_epa - a.off_epa
    def_gap = a.def_epa - h.def_epa   # positive = home defense better
    lead = home if margin >= 0 else away
    other = away if margin >= 0 else home

    if abs(off_gap) > 0.01:
        better = home if off_gap > 0 else away
        rk = h.off_rank if better == home else a.off_rank
        why.append(f"{better} moves the ball better (offense ranked {rk})")
    if abs(def_gap) > 0.01:
        better = home if def_gap > 0 else away
        rk = h.def_rank if better == home else a.def_rank
        why.append(f"{better} defends better (defense ranked {rk})")
    if not neutral_site and abs(margin) < 4:
        why.append(f"home field is worth about {HOME_FIELD_ADVANTAGE:.1f} of that")
    if neutral_site:
        why.append("neutral site, so no home-field credit")
    if not why:
        why.append(f"{lead} and {other} rate within noise of each other")

    disagreement = None
    if market_spread is not None:
        disagreement = margin - market_spread

    return GameLean(
        home=home, away=away, projected_margin=round(margin, 1),
        market_spread=market_spread,
        disagreement=round(disagreement, 1) if disagreement is not None else None,
        favoured=favoured,
        confident=abs(margin) >= MIN_MEANINGFUL_EDGE_PTS,
        why=why,
    )


def ratings_dict(tbl: pa.Table) -> dict[str, TeamRating]:
    return {
        r["team"]: TeamRating(
            team=r["team"], off_epa=r["off_epa"], def_epa=r["def_epa"],
            net=r["net"], off_rank=int(r["off_rank"]), def_rank=int(r["def_rank"]),
        )
        for r in tbl.to_pylist()
    }
