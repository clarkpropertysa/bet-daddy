"""Publish this week's injury report, with the measured probability attached.

The report has only ever existed as Parquet read by the projection. That was enough for
the model and not enough for the reader: the number that makes it refuse to price a
player -- 34.3% for a listed player who did not practise -- was unreachable from any
page. A card could say a teammate's effect was "not measurable" and could not say that
the teammate may well not play.

The RATE comes from a completed season and the STATUS from this week, the same
separation `model/project.py` uses. Measuring rates on the season being projected is
structurally empty in week 1 and was the reason `p_inactive` read zero for so long.
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import duckdb

from pipeline.common import config, db
from pipeline.features.availability import build_inactivity_table, status_lookup

SOURCE = "nflverse:/injuries"


def current_week(schedule_path: str, season: int) -> int:
    """The week now being played, or the next one.

    Derived here rather than in the workflow. It lived in a shell block with a nested
    Python heredoc, which broke the YAML outright -- the job did not fail, it failed to
    parse, and GitHub reported "a workflow file issue" with no log to read. Logic that
    needs quoting this careful does not belong in a `run:` step.
    """
    try:
        row = duckdb.connect().execute(f"""
            select min(week) from read_parquet('{schedule_path}')
            where season = {int(season)}
              and cast(gameday as date) >= current_date - 1
        """).fetchone()
    except Exception:
        return 1
    return int(row[0]) if row and row[0] is not None else 1


def collect(
    injuries_path: str,
    rates_injuries_path: str,
    snaps_path: str,
    players_path: str,
    season: int,
    week: int,
    rates_season: int,
) -> list[dict]:
    table = build_inactivity_table(
        rates_injuries_path, snaps_path, players_path, rates_season)
    status = status_lookup(injuries_path, season, week)

    try:
        rows = duckdb.connect().execute(f"""
            select gsis_id,
                   nullif(trim(coalesce(report_status,'')), '')   as report_status,
                   nullif(trim(coalesce(practice_status,'')), '') as practice_status,
                   nullif(trim(coalesce(practice_primary_injury,'')), '') as injury
            from read_parquet('{injuries_path}')
            where gsis_id is not null
              and season = {int(season)} and week = {int(week)}
        """).fetchall()
    except Exception:
        return []

    out = []
    for gsis, report, practice, injury in rows:
        p = None
        if not table.is_empty:
            # for_player takes the (report, practice) pair exactly as the projection
            # does, so the number on the card is the number the model used.
            p = table.for_player(status.get(gsis))
        out.append({
            "gsis": gsis, "season": season, "week": week,
            "report": report, "practice": practice, "injury": injury,
            "p_inactive": round(float(p), 4) if p is not None else None,
        })
    return out


def write(rows: list[dict]) -> int:
    import psycopg

    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        # Only players we already know. An unresolved gsis_id has no card to show it on.
        cur.execute('select "gsisId", id from "Player" where "gsisId" is not null')
        known = dict(cur.fetchall())
        params = [
            (str(uuid.uuid4()), known[r["gsis"]], r["season"], r["week"],
             r["report"], r["practice"], r["injury"], r["p_inactive"], SOURCE, now)
            for r in rows if r["gsis"] in known
        ]
        if not params:
            return 0
        cur.executemany(
            '''insert into "Injury" (id,"playerId",season,week,"reportStatus",
                                     "practiceStatus","primaryInjury","pInactive",
                                     source,"ingestedAt")
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict ("playerId",season,week) do update set
                 "reportStatus"   = excluded."reportStatus",
                 "practiceStatus" = excluded."practiceStatus",
                 "primaryInjury"  = excluded."primaryInjury",
                 "pInactive"      = excluded."pInactive",
                 "ingestedAt"     = excluded."ingestedAt"''',
            params,
        )
    return len(params)


def main():
    ap = argparse.ArgumentParser(description="Publish the injury report to Neon")
    ap.add_argument("--injuries", default="data/raw/nflverse/injuries_2026.parquet")
    ap.add_argument("--rates-injuries",
                    default="data/raw/nflverse/injuries_2025.parquet")
    ap.add_argument("--snaps", default="data/raw/nflverse/snap_counts_2025.parquet")
    ap.add_argument("--players", default="data/raw/nflverse/players.parquet")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--rates-season", type=int, default=2025)
    ap.add_argument("--schedule", default="data/raw/nflverse/schedules.parquet")
    ap.add_argument("--week", type=int, default=None,
                    help="omit to derive the current week from the schedule")
    a = ap.parse_args()

    if a.week is None:
        a.week = current_week(a.schedule, a.season)
        print(f"week derived from the schedule: {a.week}")

    with db.track("sync_injuries") as run:
        rows = collect(a.injuries, a.rates_injuries, a.snaps, a.players,
                       a.season, a.week, a.rates_season)
        n = write(rows)
        run["rows"] = n
        run["meta"] = {"listed": len(rows), "written": n,
                       "with_probability": sum(1 for r in rows
                                               if r["p_inactive"] is not None)}

    print(f"week {a.week}: listed={len(rows)} written={n}")
    if rows and not any(r["p_inactive"] is not None for r in rows):
        print("  WARNING: no row carries a probability. The rate table did not build "
              "-- check that --rates-injuries and --snaps cover --rates-season.")
    for r in sorted([r for r in rows if r["p_inactive"]],
                    key=lambda x: -x["p_inactive"])[:6]:
        print(f"  {r['gsis']}  {r['practice'] or r['report']}  "
              f"p_inactive={r['p_inactive']:.3f}  {r['injury'] or ''}")


if __name__ == "__main__":
    main()
