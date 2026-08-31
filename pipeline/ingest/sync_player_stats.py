"""Sync per-player game logs and teammate splits into Postgres.

Why this job has to exist: Postgres deliberately holds engineered outputs only, because
Neon's free tier is ~0.5GB and 25 seasons of play-by-play will not fit. That was the right
call, but it means the deployed Next app -- which has no DuckDB and cannot see the
gitignored Parquet -- has no access to any player statistic at all. Every number on the
player page has to be materialised here first.

The computation is not new. `usage.build_player_game_usage`, `usage.rolling_usage` and
`splits.build_with_without` already exist, are tested, and until now fed only the
projection job in memory. This persists their output.

Follows the sync_context.py pattern exactly: DuckDB for the Parquet read, psycopg imported
inside the function so the module stays importable without a database, one connection, an
idempotent upsert per row keyed on the natural identifier.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import duckdb
import pyarrow.parquet as pq

from pipeline.common import config, db
from pipeline.features.splits import build_availability, build_with_without
from pipeline.features.usage import build_player_game_usage

SOURCE = "nflverse"

# Only skill positions carry props, and syncing 2,887 rostered players would be mostly
# offensive linemen who will never appear on the board.
SKILL = ("QB", "RB", "FB", "WR", "TE")


def _box_scores(stats_path: str, season: int) -> dict[tuple[str, int], dict]:
    """(player_id, week) -> box-score line, from nflverse's own weekly stats.

    Keyed on week rather than game_id: the weekly stats file has no game_id column, and
    a player has exactly one regular-season game per week.
    """
    con = duckdb.connect()
    rows = con.execute(f"""
        select player_id, week, team, opponent_team,
               targets, receptions, receiving_yards, receiving_tds, receiving_air_yards,
               carries, rushing_yards, rushing_tds,
               passing_yards, passing_tds, passing_interceptions
        from read_parquet('{stats_path}')
        where season = {int(season)} and season_type = 'REG' and player_id is not null
    """).fetchall()
    out = {}
    for r in rows:
        out[(r[0], int(r[1]))] = {
            "team": r[2], "opponent": r[3],
            "targets": r[4], "receptions": r[5], "receiving_yards": r[6],
            "receiving_tds": r[7], "air_yards": r[8],
            "carries": r[9], "rushing_yards": r[10], "rushing_tds": r[11],
            "passing_yards": r[12], "passing_tds": r[13], "interceptions": r[14],
        }
    return out


def _snaps(snap_counts_path: str, players_path: str) -> dict[tuple[str, str], dict]:
    """(player_id, game_id) -> snap counts, via the pfr->gsis join splits.py already does."""
    try:
        tbl = build_availability(snap_counts_path, players_path)
    except Exception:
        # Snap counts are the least essential column here and the most fragile join.
        # Losing them must not cost the whole game log.
        return {}
    return {
        (r["player_id"], r["game_id"]): r
        for r in tbl.to_pylist()
        if r.get("player_id") and r.get("game_id")
    }


def sync_game_stats(
    pbp_path: str, stats_path: str, snap_counts_path: str, players_path: str, season: int
) -> int:
    import psycopg

    usage = build_player_game_usage(pbp_path).to_pylist()
    box = _box_scores(stats_path, season)
    snaps = _snaps(snap_counts_path, players_path)
    now = datetime.now(timezone.utc)

    params = []
    for u in usage:
        pid, gid = u.get("player_id"), u.get("game_id")
        if not pid or not gid:
            continue
        if int(u.get("season") or 0) != season:
            continue
        week = int(u.get("week") or 0)
        b = box.get((pid, week), {})
        s = snaps.get((pid, gid), {})
        params.append(
            (f"{pid}:{gid}", f"nfl:{pid}", gid, season, week,
             u.get("team") or b.get("team") or "", b.get("opponent"),
             _int(s.get("offense_snaps")), _float(s.get("offense_pct")),
             _int(b.get("targets")), _int(b.get("receptions")),
             _float(b.get("receiving_yards")), _int(b.get("receiving_tds")),
             _float(b.get("air_yards")),
             _int(b.get("carries")), _float(b.get("rushing_yards")),
             _int(b.get("rushing_tds")),
             _float(b.get("passing_yards")), _int(b.get("passing_tds")),
             _int(b.get("interceptions")),
             _float(u.get("target_share")), _float(u.get("air_yards_share")),
             _float(u.get("carry_share")), _float(u.get("wopr")),
             SOURCE, now)
        )

    if not params:
        return 0

    # executemany, not a loop of execute. psycopg3 pipelines it into far fewer round
    # trips; row-by-row over a network connection took minutes for this many rows and
    # would have timed out in CI.
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        cur.executemany(
            """
                insert into "PlayerGameStat"
                  (id, "playerId", "gameId", season, week, team, opponent,
                   "offenseSnaps", "offensePct",
                   targets, receptions, "receivingYards", "receivingTds", "airYards",
                   carries, "rushingYards", "rushingTds",
                   "passingYards", "passingTds", interceptions,
                   "targetShare", "airYardsShare", "carryShare", wopr,
                   source, "ingestedAt")
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s)
                on conflict ("playerId","gameId") do update set
                  "offenseSnaps" = excluded."offenseSnaps",
                  "offensePct"   = excluded."offensePct",
                  targets = excluded.targets, receptions = excluded.receptions,
                  "receivingYards" = excluded."receivingYards",
                  "receivingTds" = excluded."receivingTds",
                  "airYards" = excluded."airYards",
                  carries = excluded.carries, "rushingYards" = excluded."rushingYards",
                  "rushingTds" = excluded."rushingTds",
                  "passingYards" = excluded."passingYards",
                  "passingTds" = excluded."passingTds",
                  interceptions = excluded.interceptions,
                  "targetShare" = excluded."targetShare",
                  "airYardsShare" = excluded."airYardsShare",
                  "carryShare" = excluded."carryShare",
                  wopr = excluded.wopr,
                  "ingestedAt" = excluded."ingestedAt"
                """,
            params,
        )
    return len(params)


def sync_splits(
    pbp_path: str, snap_counts_path: str, players_path: str, season: int,
    metric: str = "target_share",
) -> dict:
    """Persist with/without-teammate splits, gates and all.

    Rows that FAIL their gates are stored too, with `significant`/`suppressed` intact.
    The UI filters on them; it does not re-derive them. Same contract player_volume.py
    honours, and it lets the page distinguish "no trustworthy split" from "not computed".
    """
    import psycopg

    usage = build_player_game_usage(pbp_path)
    avail = build_availability(snap_counts_path, players_path)
    players = pq.read_table(players_path)
    tbl = build_with_without(usage, avail, players, metric=metric)
    rows = tbl.to_pylist()
    now = datetime.now(timezone.utc)

    params, kept = [], 0
    for r in rows:
        pid, tid = r.get("player_id"), r.get("teammate_id")
        if not pid or not tid:
            continue
        params.append(
            (f"{pid}:{tid}:{metric}:{season}", f"nfl:{pid}", f"nfl:{tid}",
             r.get("team") or "", metric, season,
             _int(r.get("n_with")) or 0, _int(r.get("n_without")) or 0,
             _float(r.get("mean_with")) or 0.0, _float(r.get("mean_without")) or 0.0,
             _float(r.get("delta")) or 0.0,
             _float(r.get("ci_low")) or 0.0, _float(r.get("ci_high")) or 0.0,
             bool(r.get("significant")), bool(r.get("suppressed")),
             bool(r.get("confound_regulars_out")), SOURCE, now)
        )
        if r.get("significant") and not r.get("suppressed"):
            kept += 1

    if not params:
        return {"rows": 0, "trustworthy": 0}

    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        cur.executemany(
            """
                insert into "PlayerSplit"
                  (id, "playerId", "teammateId", team, metric, season,
                   "nWith", "nWithout", "meanWith", "meanWithout", delta,
                   "ciLow", "ciHigh", significant, suppressed, "confoundRegularsOut",
                   source, "ingestedAt")
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict ("playerId","teammateId",metric,season) do update set
                  "nWith" = excluded."nWith", "nWithout" = excluded."nWithout",
                  "meanWith" = excluded."meanWith",
                  "meanWithout" = excluded."meanWithout",
                  delta = excluded.delta,
                  "ciLow" = excluded."ciLow", "ciHigh" = excluded."ciHigh",
                  significant = excluded.significant,
                  suppressed = excluded.suppressed,
                  "confoundRegularsOut" = excluded."confoundRegularsOut",
                  "ingestedAt" = excluded."ingestedAt"
                """,
            params,
        )
    return {"rows": len(params), "trustworthy": kept}


def _int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f   # NaN is not a number the UI can render


def main():
    ap = argparse.ArgumentParser(description="Sync player game logs and splits into Neon")
    ap.add_argument("--season", type=int, default=2025,
                    help="the season whose game log to sync. 2026 has no games until "
                         "week 1, so the player page shows 2025 until then.")
    a = ap.parse_args()

    raw = config.RAW_DIR / "nflverse"
    pbp = str(raw / f"pbp_{a.season}.parquet")
    stats = str(raw / f"player_stats_week_{a.season}.parquet")
    snaps = str(raw / f"snap_counts_{a.season}.parquet")
    players = str(raw / "players.parquet")

    with db.track("sync_player_stats") as run:
        g = sync_game_stats(pbp, stats, snaps, players, a.season)
        sp = sync_splits(pbp, snaps, players, a.season)
        run["rows"] = g + sp["rows"]
        run["meta"] = {"season": a.season, "game_stats": g,
                       "splits": sp["rows"], "trustworthy_splits": sp["trustworthy"]}

    print(f"season={a.season} game_stats={g} splits={sp['rows']} "
          f"trustworthy={sp['trustworthy']}")
    # An inert sync looks identical to a working one from the outside. Same reason
    # project.py reports with_adjustments and share_based.
    if g == 0:
        print("  WARNING: no game stats written. Check that pbp and weekly stats exist "
              f"for {a.season} -- a season that has not started yet produces nothing.")
    if sp["trustworthy"] == 0 and sp["rows"]:
        print(f"  NOTE: {sp['rows']} splits computed, none clear both gates. Expected: "
              "most player pairs do not have 4+ games each way with a separable effect.")


if __name__ == "__main__":
    main()
