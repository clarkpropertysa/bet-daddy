"""nflverse ingestion via direct release-asset Parquet URLs.

Deliberately NOT using nflreadpy as the primary path. The release assets are static,
fast, unauthenticated, and immune to the client lagging a schema change -- which is a
live risk, not a hypothetical: depth_charts_2026 DROPPED jersey_number/full_name/
depth_team and replaced them with pos_abb/pos_slot/pos_rank (verified 2026-08-28).

Every dataset declares the columns we depend on. Ingest fails loudly on drift rather
than silently producing null features downstream.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from pipeline.common import config

BASE = "https://github.com/nflverse/nflverse-data/releases/download"


@dataclass(frozen=True)
class Dataset:
    name: str
    release: str
    filename: str          # may contain {season}
    seasonal: bool
    # columns we actually depend on. drift here breaks features -> fail the run.
    required: tuple[str, ...] = field(default=())
    # Alternative column sets that are ALSO acceptable. Upstream sometimes reshapes a
    # dataset at a season boundary, and both shapes are then legitimately published
    # forever. Satisfying any one set passes; satisfying none is real drift.
    alternates: tuple[tuple[str, ...], ...] = field(default=())


DATASETS = {
    "pbp": Dataset("pbp", "pbp", "play_by_play_{season}.parquet", True,
                   ("game_id", "play_id", "posteam", "defteam", "epa", "air_yards",
                    "yards_after_catch", "receiver_player_id", "rusher_player_id",
                    "passer_player_id", "week", "season")),
    "player_stats_week": Dataset("player_stats_week", "stats_player",
                                 "stats_player_week_{season}.parquet", True,
                                 ("player_id", "player_display_name", "season", "week",
                                  "team", "opponent_team", "season_type", "passing_yards",
                                  "receiving_yards", "rushing_yards", "receptions",
                                  "targets", "passing_tds")),
    "snap_counts": Dataset("snap_counts", "snap_counts", "snap_counts_{season}.parquet", True,
                           ("game_id", "pfr_player_id", "player", "team", "offense_snaps",
                            "offense_pct", "week", "season")),
    "injuries": Dataset("injuries", "injuries", "injuries_{season}.parquet", True,
                        ("season", "week", "team", "gsis_id", "report_status")),
    "rosters_weekly": Dataset("rosters_weekly", "weekly_rosters",
                              "roster_weekly_{season}.parquet", True,
                              ("season", "team", "position", "jersey_number", "full_name",
                               "first_name", "last_name", "gsis_id", "week")),
    # nflverse reshaped depth charts at the 2025 boundary. 2024 and earlier publish
    # club_code/depth_position/full_name; 2025 onward publish team/player_name/
    # pos_abb/pos_rank. Both are still served, so requiring only the new shape failed
    # the ENTIRE daily workflow on a 2024 file -- taking reference sync, depth sync,
    # context, projections and grading down with it, every day, silently.
    "depth_charts": Dataset("depth_charts", "depth_charts", "depth_charts_{season}.parquet", True,
                            ("team", "player_name", "gsis_id", "pos_abb", "pos_rank"),
                            alternates=(
                                ("club_code", "full_name", "gsis_id", "depth_position",
                                 "depth_team"),
                            )),
    # Comprehensive cross-source ID crosswalk. Maps pfr_id -> gsis_id at 99.7%
    # coverage on 2025 snap counts; weekly rosters only manage 65.9%.
    "players": Dataset("players", "players", "players.parquet", False,
                       ("gsis_id", "pfr_id", "display_name", "position")),
    "teams": Dataset("teams", "teams", "teams_colors_logos.parquet", False,
                     ("team_abbr", "team_name", "team_color", "team_logo_espn")),
    "schedules": Dataset("schedules", "schedules", "games.parquet", False,
                         ("game_id", "season", "week", "gameday", "weekday", "gametime",
                          "away_team", "home_team", "roof", "surface", "stadium")),
}


class SchemaDriftError(RuntimeError):
    pass


class NotYetPublished(RuntimeError):
    """Asset 404s because the season has not produced data yet -- not a failure."""


def url_for(ds: Dataset, season: int | None) -> str:
    fn = ds.filename.format(season=season) if ds.seasonal else ds.filename
    return f"{BASE}/{ds.release}/{fn}"


def fetch(name: str, season: int | None = None, force: bool = False) -> pa.Table:
    ds = DATASETS[name]
    if ds.seasonal and season is None:
        raise ValueError(f"{name} is seasonal; pass season=")

    suffix = f"_{season}" if ds.seasonal else ""
    dest = config.RAW_DIR / "nflverse" / f"{name}{suffix}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if force or not dest.exists():
        u = url_for(ds, season)
        r = requests.get(u, timeout=180,
                         headers={"User-Agent": "bet-daddy/0.1 (personal research)"})
        if r.status_code == 404:
            # nflverse only publishes a season file once that season has data. A 404 on
            # the current/future season is expected, not broken -- distinguish it so the
            # pipeline does not cry wolf every run until week 1.
            raise NotYetPublished(f"{name} season {season} not published yet ({u})")
        r.raise_for_status()
        dest.write_bytes(r.content)

    df = pq.read_table(dest)
    cols = set(df.column_names)
    accepted = [ds.required, *ds.alternates]
    if not any(set(want) <= cols for want in accepted):
        missing = [c for c in ds.required if c not in cols]
        alt_note = (
            f" Also tried {len(ds.alternates)} known alternative schema(s)."
            if ds.alternates else ""
        )
        raise SchemaDriftError(
            f"{name}{suffix}: nflverse schema drift -- missing required columns {missing}."
            f"{alt_note} "
            f"Present: {sorted(cols)[:40]}... "
            f"Update DATASETS[{name!r}].required and any dependent feature code."
        )
    return df


def ingest(names: list[str], seasons: list[int], force: bool = False) -> list[dict]:
    out = []
    for name in names:
        ds = DATASETS[name]
        targets = seasons if ds.seasonal else [None]
        for s in targets:
            t0 = time.time()
            rec = {"dataset": name, "season": s, "started": datetime.now(timezone.utc)}
            try:
                df = fetch(name, s, force=force)
                rec |= {"status": "ok", "rows": df.num_rows, "cols": df.num_columns,
                        "secs": round(time.time() - t0, 1)}
            except NotYetPublished as e:
                rec |= {"status": "pending", "rows": 0, "error": str(e),
                        "secs": round(time.time() - t0, 1)}
            except Exception as e:
                rec |= {"status": "error", "rows": 0, "error": repr(e)[:300],
                        "secs": round(time.time() - t0, 1)}
            out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser(description="Ingest nflverse release Parquet")
    ap.add_argument("--datasets", default="schedules,player_stats_week,snap_counts,"
                                          "injuries,rosters_weekly,depth_charts")
    ap.add_argument("--seasons", default="2024,2025,2026")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    names = [n.strip() for n in a.datasets.split(",") if n.strip()]
    seasons = [int(s) for s in a.seasons.split(",") if s.strip()]
    results = ingest(names, seasons, force=a.force)

    ok = sum(1 for r in results if r["status"] == "ok")
    pending = sum(1 for r in results if r["status"] == "pending")
    errs = sum(1 for r in results if r["status"] == "error")
    print(f"{ok} ok, {pending} pending (season not started), {errs} error\n")
    tags = {"ok": "ok  ", "pending": "wait", "error": "FAIL"}
    for r in results:
        season = r["season"] or "-"
        print(f"  [{tags[r['status']]}] {r['dataset']:<20} {str(season):<6} "
              f"rows={r.get('rows', 0):>8,} {r.get('secs', 0)}s")
        if r["status"] == "error":
            print(f"         {r.get('error')}")

    # only real errors are non-zero exit; pending is normal preseason state
    raise SystemExit(1 if errs else 0)


if __name__ == "__main__":
    main()
