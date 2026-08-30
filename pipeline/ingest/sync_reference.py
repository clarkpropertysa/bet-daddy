"""Sync teams, players and games from the Parquet layer into Neon.

Only reference data goes to Postgres -- identity and schedule, the small tables the
web app joins against. Play-by-play stays in Parquet (Section 6).

Idempotent: every write is an upsert keyed on the natural identifier, so re-running
after a partial failure converges rather than duplicating.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timezone

import duckdb

from pipeline.common import config, db

SOURCE = "nflverse"


def _rows(sql: str, params: list | None = None) -> list[tuple]:
    return duckdb.connect().execute(sql, params or []).fetchall()


def sync_teams(schedules_path: str, season: int, teams_path: str | None = None) -> int:
    """Teams active in `season`.

    Scoping to the season matters: schedules.parquet spans every year back to 1999,
    so an unscoped query returns 35 teams -- OAK, SD and STL are relocated franchises
    that no longer exist under those codes.
    """
    import psycopg

    # Derived as a SIBLING FILE, not by rewriting a substring of the path. The old
    # form replaced "schedules.parquet" with the UPSTREAM release filename
    # (teams_colors_logos.parquet) while the ingest writes it locally as
    # teams.parquet -- so it only ever worked on a machine that happened to have an
    # older hand-fetched copy, and failed outright in CI. Substring surgery on a path
    # is the same class of bug as splitting a concatenated team code positionally.
    if teams_path is None:
        teams_path = str(Path(schedules_path).parent / "teams.parquet")

    colors = {
        r[0]: (r[1], r[2], r[3], r[4])
        for r in _rows(
            f"""select team_abbr, team_name, team_color, team_color2, team_logo_espn
                from read_parquet('{teams_path}')"""
        )
    }

    teams = _rows(f"""
        select distinct team from (
            select home_team as team from read_parquet('{schedules_path}')
              where season = {int(season)}
            union select away_team from read_parquet('{schedules_path}')
              where season = {int(season)}
        ) where team is not null
    """)
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        for (abbrev,) in teams:
            name, color, color2, logo = colors.get(abbrev, (abbrev, None, None, None))
            cur.execute(
                """
                insert into "Team" (id, sport, abbrev, name, color, color2, "logoUrl")
                values (%s, 'nfl'::"Sport", %s, %s, %s, %s, %s)
                on conflict (id) do update
                  set abbrev = excluded.abbrev, name = excluded.name,
                      color = excluded.color, color2 = excluded.color2,
                      "logoUrl" = excluded."logoUrl"
                """,
                (f"nfl:{abbrev}", abbrev, name or abbrev, color, color2, logo),
            )
    return len(teams)


def sync_players(players_path: str, roster_path: str) -> int:
    import psycopg

    rows = _rows(f"""
        select distinct
            p.gsis_id, p.display_name, coalesce(r.position, p.position) as position,
            r.team, r.headshot_url
        from read_parquet('{players_path}') p
        left join (
            select distinct gsis_id, position, team, headshot_url
            from read_parquet('{roster_path}')
            where gsis_id is not null
        ) r on r.gsis_id = p.gsis_id
        where p.gsis_id is not null and p.display_name is not null
          and r.team is not null
    """)
    now = datetime.now(timezone.utc)
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        for gsis, name, pos, team, headshot in rows:
            cur.execute(
                """
                insert into "Player"
                    (id, sport, "fullName", position, "teamId", "gsisId",
                     "headshotUrl", "externalIds", source, "ingestedAt")
                values (%s, 'nfl'::"Sport", %s, %s, %s, %s, %s, '{}'::jsonb, %s, %s)
                on conflict ("gsisId") do update
                  set "fullName"    = excluded."fullName",
                      position      = excluded.position,
                      "teamId"      = excluded."teamId",
                      "headshotUrl" = coalesce(excluded."headshotUrl",
                                               "Player"."headshotUrl")
                """,
                (f"nfl:{gsis}", name, pos, f"nfl:{team}", gsis, headshot, SOURCE, now),
            )
    return len(rows)


def sync_games(schedules_path: str, season: int) -> int:
    import psycopg

    rows = _rows(f"""
        select game_id, season, week, gameday, home_team, away_team,
               stadium, roof, surface
        from read_parquet('{schedules_path}')
        where season = {int(season)}
    """)
    now = datetime.now(timezone.utc)
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        for gid, seas, week, gameday, home, away, stadium, roof, surface in rows:
            cur.execute(
                """
                insert into "Game"
                    (id, sport, season, week, "gameDate", "homeTeamId", "awayTeamId",
                     venue, roof, surface, source, "ingestedAt")
                values (%s, 'nfl'::"Sport", %s, %s, %s::date, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update
                  set "gameDate" = excluded."gameDate", venue = excluded.venue,
                      roof = excluded.roof, surface = excluded.surface
                """,
                (gid, seas, week, gameday, f"nfl:{home}", f"nfl:{away}",
                 stadium, roof, surface, SOURCE, now),
            )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Sync reference data into Neon")
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()

    raw = config.RAW_DIR / "nflverse"
    sched = str(raw / "schedules.parquet")

    with db.track("sync_reference") as run:
        t = sync_teams(sched, a.season, str(raw / "teams.parquet"))
        p = sync_players(str(raw / "players.parquet"),
                         str(raw / f"rosters_weekly_{a.season}.parquet"))
        g = sync_games(sched, a.season)
        run["rows"] = t + p + g
        run["meta"] = {"teams": t, "players": p, "games": g}
    print(f"teams={t} players={p} games={g}")


if __name__ == "__main__":
    main()
