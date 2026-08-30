"""Context that makes an explanation specific rather than generic.

"He averaged 11.6 targets" is a fact, not an argument. What makes a projection
arguable is the surrounding detail: whether that number is rising or falling, how
much of his offense he commands, which specific defensive weakness he faces, and how
often he has actually cleared this line.

Everything here is READ FROM PLAY-BY-PLAY, and every field carries its own sample
size, because a three-game trend and a sixteen-game trend are different claims.

Historical clearance rate is included deliberately and labelled carefully. Section 2
is emphatic that a hit rate is not a signal — the line has already absorbed it. It is
here as CONTEXT beside the model's probability, never as the reason, and the UI must
present it that way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

RECENT_GAMES = 3


@dataclass
class PropContext:
    # form
    season_mean: float | None = None
    recent_mean: float | None = None
    recent_games: int = 0
    trend_pct: float | None = None
    # usage
    target_share: float | None = None
    share_rank_on_team: int | None = None
    teammates_counted: int = 0
    # matchup
    def_metric: float | None = None
    def_rank: int | None = None
    def_split: str | None = None
    # outcome history at this line
    clearance_n: int = 0
    clearance_hits: int = 0
    # availability
    games_played: int = 0
    team_games: int = 0
    notes: list[str] = field(default_factory=list)


_VOLUME_SQL = {
    "targets": "receiver_player_id",
    "carries": "rusher_player_id",
    "pass attempts": "passer_player_id",
    "red-zone touches": "coalesce(receiver_player_id, rusher_player_id)",
}

_OUTCOME_SQL = {
    "rec_yds": ("receiver_player_id", "yards_gained", "complete_pass = 1"),
    "receptions": ("receiver_player_id", "1", "complete_pass = 1"),
    "rush_yds": ("rusher_player_id", "yards_gained", "1=1"),
    "pass_yds": ("passer_player_id", "yards_gained", "complete_pass = 1"),
    "pass_tds": ("passer_player_id", "coalesce(pass_touchdown,0)", "1=1"),
}


def load_context(
    pbp_path: str, player_id: str, team: str | None,
    market_type: str, volume_metric: str, strike: float | None,
    season_type: str = "REG",
) -> PropContext:
    con = duckdb.connect()
    ctx = PropContext()
    vol_col = _VOLUME_SQL.get(volume_metric)
    base = f"""
        select * from read_parquet('{pbp_path}')
        where season_type = '{season_type}'
          and coalesce(two_point_attempt,0)=0 and coalesce(qb_kneel,0)=0
          and play_type in ('pass','run')
    """
    con.execute(f"create or replace view plays as {base}")

    # ---- form: season mean vs the last N games -------------------------------
    if vol_col:
        rows = con.execute(f"""
            select game_id, count(*) n
            from plays where {vol_col} = ?
            group by 1 order by min(week)
        """, [player_id]).fetchall()
        if rows:
            counts = [r[1] for r in rows]
            ctx.games_played = len(counts)
            ctx.season_mean = sum(counts) / len(counts)
            recent = counts[-RECENT_GAMES:]
            ctx.recent_games = len(recent)
            ctx.recent_mean = sum(recent) / len(recent)
            if ctx.season_mean:
                ctx.trend_pct = (ctx.recent_mean - ctx.season_mean) / ctx.season_mean

    # ---- usage share within his own offense ---------------------------------
    if team and volume_metric == "targets":
        share = con.execute("""
            with tt as (
                select receiver_player_id pid, count(*) n from plays
                where posteam = ? and receiver_player_id is not null group by 1
            ),
            tot as (select sum(n) t from tt)
            select
              (select n from tt where pid = ?)::double / (select t from tot),
              (select count(*) from tt where n > coalesce((select n from tt where pid = ?),0)) + 1,
              (select count(*) from tt)
        """, [team, player_id, player_id]).fetchone()
        if share and share[0] is not None:
            ctx.target_share, ctx.share_rank_on_team, ctx.teammates_counted = (
                float(share[0]), int(share[1]), int(share[2]))

    # ---- how often he has actually cleared this line ------------------------
    spec = _OUTCOME_SQL.get(market_type)
    if spec and strike is not None:
        col, val, cond = spec
        r = con.execute(f"""
            with per_game as (
                select game_id, sum({val}) total
                from plays where {col} = ? and {cond}
                group by 1
            )
            select count(*), sum(case when total > ? then 1 else 0 end) from per_game
        """, [player_id, strike]).fetchone()
        if r and r[0]:
            ctx.clearance_n, ctx.clearance_hits = int(r[0]), int(r[1] or 0)

    return ctx


def defense_detail(
    pass_grades, rush_grades, opponent: str, market_type: str, position: str | None,
) -> tuple[float | None, int | None, str | None]:
    """The specific defensive split this prop runs into, not a team-level average."""
    con = duckdb.connect()
    if market_type in ("rush_yds",):
        con.register("g", rush_grades)
        r = con.execute("""
            select epa_per_carry, epa_rank from g
            where team = ? and run_location = 'all' and rankable
        """, [opponent]).fetchone()
        return (r[0], int(r[1]) if r and r[1] else None, "the run") if r else (None, None, None)

    con.register("g", pass_grades)
    pos = position if position in ("WR", "TE", "RB") else None
    if pos:
        r = con.execute("""
            select avg(epa_per_target), min(epa_rank) from g
            where team = ? and receiver_position = ? and rankable
        """, [opponent, pos]).fetchone()
        if r and r[0] is not None:
            return (r[0], int(r[1]) if r[1] else None, f"passes to {pos}s")
    r = con.execute("""
        select avg(epa_per_target), min(epa_rank) from g where team = ? and rankable
    """, [opponent]).fetchone()
    return (r[0], int(r[1]) if r and r[1] else None, "the pass") if r else (None, None, None)
