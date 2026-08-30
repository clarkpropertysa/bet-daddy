"""Write per-game schedule context into Neon for the Slate.

Rest, venue, line and weather facts are engineered outputs and belong in Postgres
(Section 6). The play-by-play they derive from stays in Parquet.

USE NFLVERSE'S OWN FIELDS. The schedule already carries `location` (Home/Neutral),
`home_rest`/`away_rest`, `total_line`, `spread_line`, `temp` and `wind`. An earlier
version of this module inferred neutral sites by comparing each game's stadium to the
team's most-frequent stadium, which flagged 55 of 272 games in 2026 -- stadiums get
renamed (Seattle's all-time leader is "CenturyLink Field" at 81 games against Lumen
Field's 58), so every Seattle home game read as neutral. The authoritative column says
8, all genuinely international.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import duckdb

from pipeline.common import config, db
from pipeline.features.rest import build
from pipeline.ingest.nflverse import fetch
from pipeline.model.team_rating import build_ratings, project_game, ratings_dict

# Section 5.5: wind is the weather variable that matters for passing and kicking,
# and the threshold is roughly 15mph. Temperature mostly is not.
WIND_THRESHOLD_MPH = 15


def sync(season: int, pbp_path: str | None = None) -> dict:
    import psycopg

    sched = fetch("schedules")
    # Ratings come from the PRIOR season, so a projection for `season` is genuinely
    # out of sample.
    ratings = None
    if pbp_path:
        try:
            ratings = ratings_dict(build_ratings(pbp_path))
        except Exception:
            ratings = None
    rest = build(sched, season=season)

    con = duckdb.connect()
    con.register("rest", rest)
    con.register("sched", sched)

    games = con.execute(f"""
        select game_id, total_line, spread_line, roof, surface, stadium,
               temp, wind, location, div_game, home_qb_name, away_qb_name,
               home_team, away_team
        from sched where season = {int(season)}
    """).fetchall()

    ctx = con.execute(f"""
        select r.game_id, r.team, r.days_rest, r.is_short_week, r.is_post_bye,
               r.games_in_last_6
        from rest r where r.season = {int(season)}
    """).fetchall()

    now = datetime.now(timezone.utc)
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        for (gid, total, spread, roof, surface, stadium, temp, wind, loc,
             div_game, hqb, aqb, home, away) in games:
            neutral = (loc or "Home") != "Home"
            lean = (project_game(home, away, ratings, spread, neutral)
                    if ratings else None)
            cur.execute(
                '''update "Game"
                   set "totalLine" = %s, "spreadLine" = %s, roof = %s, surface = %s,
                       venue = %s, "tempF" = %s, "windMph" = %s,
                       "isNeutral" = %s, "divGame" = %s, "homeQb" = %s, "awayQb" = %s,
                       "projMargin" = %s, "leanTeam" = %s, "leanConfident" = %s,
                       "leanWhy" = %s::jsonb, "leanDisagreement" = %s
                   where id = %s''',
                (total, spread, roof, surface, stadium, temp, wind,
                 neutral, bool(div_game), hqb, aqb,
                 lean.projected_margin if lean else None,
                 lean.favoured if lean else None,
                 bool(lean.confident) if lean else False,
                 json.dumps(lean.why) if lean else None,
                 lean.disagreement if lean else None,
                 gid),
            )
        for gid, team, days_rest, short_week, post_bye, g6 in ctx:
            cur.execute(
                '''insert into "GameContext"
                     (id, "gameId", "teamId", "daysRest", "isShortWeek", "isPostBye",
                      "gamesInLast6", source, "ingestedAt")
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict ("gameId","teamId") do update
                     set "daysRest" = excluded."daysRest",
                         "isShortWeek" = excluded."isShortWeek",
                         "isPostBye" = excluded."isPostBye",
                         "gamesInLast6" = excluded."gamesInLast6"''',
                (f"{gid}:{team}", gid, f"nfl:{team}", days_rest,
                 bool(short_week), bool(post_bye), int(g6 or 0), "nflverse", now),
            )
    return {"games": len(games), "context_rows": len(ctx)}


def main():
    ap = argparse.ArgumentParser(description="Sync per-game schedule context")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--ratings-pbp", default=None,
                    help="prior-season pbp used for team EPA ratings")
    a = ap.parse_args()
    with db.track("sync_context") as run:
        r = sync(a.season, a.ratings_pbp)
        run["rows"] = r["context_rows"]
        run["meta"] = r
    print(f"games={r['games']} context_rows={r['context_rows']}")


if __name__ == "__main__":
    main()
