"""Team strength from EPA, with prior-season ratings shrunk toward the mean.

MEASURED, NOT ASSUMED: a team's net EPA per play in one season predicts the next
season only weakly.

    year-over-year correlation, 2022->23, 23->24, 24->25 (96 team-seasons)
        r = 0.344,  r^2 = 0.118,  optimal regression slope = 0.37

Twelve percent of variance. Offseasons change rosters, coordinators and quarterbacks,
and the rating does not know that. So a prior-season rating is shrunk to 0.37 of its
distance from league average before it is used at all.

Refitting the margin model with shrunk ratings, strictly out of sample (prior-season
ratings predicting the following season, 816 games):

    47.0 points per shrunk net EPA/play
    +2.20 points home-field advantage
    R^2 0.038,  RMSE 14.05 points

An earlier version of this module reported R^2 0.318 / RMSE 11.68. That was fitted
IN SAMPLE — ratings and results from the same season — and it flattered the model
badly. These numbers are the honest ones.

The practical consequence: with a ~14-point standard error, a projected margin under
about 3.5 points is indistinguishable from zero, and even a large lean is a weak
signal on any single game. In-season, current-season data replaces the prior as it
accumulates, because it is not shrunk and is worth far more per game.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pyarrow as pa

# Measured over 96 team-seasons. See module docstring.
PRIOR_SEASON_SHRINKAGE = 0.37
YOY_R_SQUARED = 0.118

POINTS_PER_NET_EPA = 46.95
HOME_FIELD_ADVANTAGE = 2.20
MARGIN_RMSE_PTS = 14.05

# A quarter of the standard error. Below this the lean is inside the model's noise.
MIN_MEANINGFUL_EDGE_PTS = 3.5

# Games of current-season data at which it fully replaces the prior season. Chosen so
# the blend crosses 50% around week 4-5, roughly where in-season EPA becomes the
# better predictor.
FULL_WEIGHT_GAMES = 8


@dataclass(frozen=True)
class TeamRating:
    team: str
    off_epa: float
    def_epa: float
    net: float                # already shrunk / blended, ready to use
    raw_net: float            # before shrinkage, for explanation
    off_rank: int
    def_rank: int
    games_current: int
    shrinkage: float
    off_pass: float = 0.0
    off_rush: float = 0.0
    def_pass: float = 0.0
    def_rush: float = 0.0
    off_pass_rank: int = 0
    off_rush_rank: int = 0
    def_pass_rank: int = 0
    def_rush_rank: int = 0


def _epa_query(pbp_path: str, season_type: str) -> str:
    """Team EPA, split by pass and rush.

    The split matters for explanation: "they move the ball well" is vague, while
    "they throw well and cannot run" tells a reader which unit the edge rests on and
    whether it survives a game script that forces the other one.
    """
    return f"""
        with plays as (
            select * from read_parquet('{pbp_path}')
            where season_type = '{season_type}' and epa is not null
              and play_type in ('pass','run') and coalesce(qb_kneel,0) = 0
        ),
        off as (
            select posteam team, avg(epa) off_epa,
                   avg(case when play_type='pass' then epa end) off_pass,
                   avg(case when play_type='run'  then epa end) off_rush,
                   count(distinct game_id) g
            from plays group by 1
        ),
        def as (
            select defteam team, avg(epa) def_epa,
                   avg(case when play_type='pass' then epa end) def_pass,
                   avg(case when play_type='run'  then epa end) def_rush
            from plays group by 1
        )
        select o.team, o.off_epa, d.def_epa, o.off_epa - d.def_epa as net, o.g,
               o.off_pass, o.off_rush, d.def_pass, d.def_rush
        from off o join def d on d.team = o.team
    """


def build_ratings(
    prior_pbp_path: str,
    current_pbp_path: str | None = None,
    season_type: str = "REG",
) -> pa.Table:
    """Blended team ratings.

    `prior_pbp_path` is last season and is shrunk. `current_pbp_path` is this season
    and is not — it is what actually happened to this roster.
    """
    con = duckdb.connect()
    con.execute(f"create or replace view prior as {_epa_query(prior_pbp_path, season_type)}")

    if current_pbp_path:
        con.execute(
            f"create or replace view cur as {_epa_query(current_pbp_path, season_type)}"
        )
    else:
        con.execute("create or replace view cur as select * from prior where false")

    return con.execute(f"""
        with blended as (
            select
                p.team,
                coalesce(c.g, 0) as games_current,
                least(coalesce(c.g, 0)::double / {FULL_WEIGHT_GAMES}, 1.0) as w,
                p.net as prior_net,
                c.net as cur_net,
                coalesce(c.off_epa, p.off_epa) as off_epa,
                coalesce(c.def_epa, p.def_epa) as def_epa,
                coalesce(c.off_pass, p.off_pass) as off_pass,
                coalesce(c.off_rush, p.off_rush) as off_rush,
                coalesce(c.def_pass, p.def_pass) as def_pass,
                coalesce(c.def_rush, p.def_rush) as def_rush
            from prior p left join cur c on c.team = p.team
        ),
        rated as (
            select team, games_current, off_epa, def_epa,
                   off_pass, off_rush, def_pass, def_rush,
                   prior_net as raw_net,
                   -- prior season is shrunk; current season is not
                   (1 - w) * (prior_net * {PRIOR_SEASON_SHRINKAGE})
                     + w * coalesce(cur_net, 0) as net,
                   case when games_current >= {FULL_WEIGHT_GAMES}
                        then 1.0 else {PRIOR_SEASON_SHRINKAGE} end as shrinkage
            from blended
        )
        select *,
               rank() over (order by off_epa desc)  as off_rank,
               rank() over (order by def_epa asc)   as def_rank,
               rank() over (order by off_pass desc) as off_pass_rank,
               rank() over (order by off_rush desc) as off_rush_rank,
               rank() over (order by def_pass asc)  as def_pass_rank,
               rank() over (order by def_rush asc)  as def_rush_rank
        from rated order by net desc
    """).to_arrow_table()


@dataclass(frozen=True)
class GameLean:
    home: str
    away: str
    projected_margin: float
    market_spread: float | None
    disagreement: float | None
    favoured: str
    confident: bool
    why: list[str]


def project_game(
    home: str, away: str, ratings: dict[str, TeamRating],
    market_spread: float | None = None, neutral_site: bool = False,
    home_qb: str | None = None, away_qb: str | None = None,
    prior_home_qb: str | None = None, prior_away_qb: str | None = None,
) -> GameLean | None:
    h, a = ratings.get(home), ratings.get(away)
    if not h or not a:
        return None

    hfa = 0.0 if neutral_site else HOME_FIELD_ADVANTAGE
    margin = (h.net - a.net) * POINTS_PER_NET_EPA + hfa
    favoured = home if margin >= 0 else away

    why: list[str] = []
    on_prior = h.games_current < FULL_WEIGHT_GAMES

    # Lead with WHERE the rating comes from — that is the biggest caveat before week 4.
    if on_prior:
        why.append(
            f"Built on last season's play, shrunk to {int(PRIOR_SEASON_SHRINKAGE * 100)}% "
            f"— prior-season EPA explains only {int(YOY_R_SQUARED * 100)}% of the next "
            f"season, so it is a weak prior, not a read on this roster"
        )
    else:
        why.append(
            f"Built on {h.games_current} games of this season, which has replaced the "
            f"prior-season prior"
        )

    # Name the specific units, and where they meet. "Moves the ball well" is vague;
    # "throws well into a defence that cannot cover" says which matchup carries it.
    lead, trail = (h, a) if margin >= 0 else (a, h)
    lead_name = home if margin >= 0 else away
    trail_name = away if margin >= 0 else home

    if lead.off_pass_rank and trail.def_pass_rank:
        why.append(
            f"{lead_name} throws it {_ord(lead.off_pass_rank)}-best "
            f"({lead.off_pass:+.3f} EPA/dropback) into a pass defense ranked "
            f"{_ord(trail.def_pass_rank)}"
        )
    if lead.off_rush_rank and trail.def_rush_rank:
        why.append(
            f"On the ground {lead_name} is {_ord(lead.off_rush_rank)} "
            f"({lead.off_rush:+.3f} EPA/carry) against a run defense ranked "
            f"{_ord(trail.def_rush_rank)}"
        )

    # Which side of the ball is actually carrying the lean. Without this a
    # defense-driven edge reads as an offensive one, or as nothing at all.
    off_edge = lead.off_epa - trail.off_epa
    def_edge = trail.def_epa - lead.def_epa
    if abs(off_edge) > 0.005 or abs(def_edge) > 0.005:
        carrier = "defense" if def_edge > off_edge else "offense"
        why.append(
            f"The lean is carried by {lead_name}'s {carrier} "
            f"({_ord(lead.def_rank if carrier == 'defense' else lead.off_rank)} of 32), "
            f"not by both units"
            if abs(def_edge - off_edge) > 0.02 else
            f"{lead_name} rates ahead on both sides of the ball"
        )

    # the counter-argument, so a reader sees what beats this
    if trail.off_pass_rank and trail.off_pass_rank <= 12:
        why.append(
            f"{trail_name} is not passive — {_ord(trail.off_pass_rank)} throwing the "
            f"ball, which is where an upset comes from"
        )
    elif trail.def_pass_rank and trail.def_pass_rank <= 10:
        why.append(
            f"{trail_name} defends the pass well ({_ord(trail.def_pass_rank)}), which "
            f"is the most likely way this margin fails to appear"
        )

    # A changed quarterback invalidates most of an offensive rating.
    for team, qb, prior_qb in ((home, home_qb, prior_home_qb), (away, away_qb, prior_away_qb)):
        if qb and prior_qb and qb != prior_qb:
            why.append(
                f"{team} has a different quarterback ({qb}, was {prior_qb}) — the "
                f"offensive rating largely describes someone else"
            )

    if neutral_site:
        why.append("Neutral site, so no home-field credit")
    elif abs(margin) < 6:
        why.append(f"Home field is {HOME_FIELD_ADVANTAGE:.1f} of that margin")

    disagreement = margin - market_spread if market_spread is not None else None

    return GameLean(
        home=home, away=away, projected_margin=round(margin, 1),
        market_spread=market_spread,
        disagreement=round(disagreement, 1) if disagreement is not None else None,
        favoured=favoured,
        confident=abs(margin) >= MIN_MEANINGFUL_EDGE_PTS,
        why=why,
    )


def _ord(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def ratings_dict(tbl: pa.Table) -> dict[str, TeamRating]:
    return {
        r["team"]: TeamRating(
            team=r["team"], off_epa=r["off_epa"], def_epa=r["def_epa"],
            net=r["net"], raw_net=r["raw_net"],
            off_rank=int(r["off_rank"]), def_rank=int(r["def_rank"]),
            games_current=int(r["games_current"]), shrinkage=float(r["shrinkage"]),
            off_pass=r["off_pass"] or 0.0, off_rush=r["off_rush"] or 0.0,
            def_pass=r["def_pass"] or 0.0, def_rush=r["def_rush"] or 0.0,
            off_pass_rank=int(r["off_pass_rank"] or 0),
            off_rush_rank=int(r["off_rush_rank"] or 0),
            def_pass_rank=int(r["def_pass_rank"] or 0),
            def_rush_rank=int(r["def_rush_rank"] or 0),
        )
        for r in tbl.to_pylist()
    }
