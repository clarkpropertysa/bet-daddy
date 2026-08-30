"""Depth-chart standing, and injury-driven promotion.

Most rostered players never see a meaningful snap: 2,887 players carry props for
maybe 220. The prop-relevant set is defined by depth-chart rank, per position:

    QB 1      one passer takes essentially every dropback
    RB 1-2    backfields are committees more often than not
    WR 1-3    three-receiver sets are the base personnel
    TE 1      TE2 rarely draws enough targets to price

When a starter is ruled Out or Doubtful, the next man at that position is promoted
and carries `promotedFor` so the UI can say WHY he is on the board -- a backup who
appears without explanation looks like a bug.

Only the LATEST depth-chart snapshot is used. The file holds 160 dated snapshots
going back to March; taking them all would return a player at every rank he has ever
held.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import duckdb

from pipeline.common import config, db

# depth ranks that carry prop-relevant usage
STARTER_DEPTH = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}

# Designations that free up the snaps below them.
OUT_STATUSES = ("Out", "Doubtful")


def _latest_depth(depth_path: str) -> str:
    return f"""
        with latest as (select max(dt) m from read_parquet('{depth_path}')),
        ranked as (
            select d.team, d.gsis_id, d.player_name, d.pos_abb, d.pos_rank,
                   row_number() over (
                       partition by d.team, d.gsis_id, d.pos_abb order by d.pos_rank
                   ) rn
            from read_parquet('{depth_path}') d, latest
            where d.dt = latest.m and d.gsis_id is not null
              and d.pos_abb in ('QB','RB','WR','TE')
        )
        select team, gsis_id, player_name, pos_abb, pos_rank
        from ranked where rn = 1
    """


def sync_depth(depth_path: str, injuries_path: str | None = None) -> dict:
    """Write depth standing and starter flags into Player."""
    import psycopg

    con = duckdb.connect()
    rows = con.execute(_latest_depth(depth_path)).fetchall()

    out_ids: set[str] = set()
    if injuries_path:
        try:
            out_ids = {
                r[0] for r in con.execute(
                    f"""select distinct gsis_id from read_parquet('{injuries_path}')
                        where report_status in {OUT_STATUSES} and gsis_id is not null"""
                ).fetchall()
            }
        except Exception:
            out_ids = set()

    # group by (team, position) so promotion can walk the ladder
    by_slot: dict[tuple[str, str], list[tuple]] = {}
    for team, gsis, name, pos, rank in rows:
        by_slot.setdefault((team, pos), []).append((rank, gsis, name))

    starters: dict[str, tuple[int, str | None]] = {}
    for (team, pos), players in by_slot.items():
        players.sort()
        depth = STARTER_DEPTH.get(pos, 1)
        available = [p for p in players if p[1] not in out_ids]
        # everyone inside the normal depth who is available
        chosen = available[:depth]
        normal_ids = {p[1] for p in players[:depth]}
        for rank, gsis, _name in chosen:
            promoted_for = None
            if gsis not in normal_ids:
                # someone ahead of him is out; name the player he is covering
                missing = [p for p in players[:depth] if p[1] in out_ids]
                promoted_for = missing[0][2] if missing else "an absent starter"
            starters[gsis] = (rank, promoted_for)

    now = datetime.now(timezone.utc)
    updated = 0
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        cur.execute('update "Player" set "isStarter" = false, "promotedFor" = null')
        for team, gsis, name, pos, rank in rows:
            st = starters.get(gsis)
            cur.execute(
                '''update "Player"
                   set "depthPos" = %s, "depthRank" = %s,
                       "isStarter" = %s, "promotedFor" = %s
                   where "gsisId" = %s''',
                (pos, rank, st is not None, st[1] if st else None, gsis),
            )
            updated += cur.rowcount
    return {"depth_rows": len(rows), "starters": len(starters),
            "injured_out": len(out_ids), "updated": updated}


def main():
    ap = argparse.ArgumentParser(description="Sync depth-chart standing")
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()
    raw = config.RAW_DIR / "nflverse"
    inj = raw / f"injuries_{a.season}.parquet"
    with db.track("sync_depth") as run:
        r = sync_depth(str(raw / f"depth_charts_{a.season}.parquet"),
                       str(inj) if inj.exists() else None)
        run["rows"] = r["updated"]
        run["meta"] = r
    print(f"depth rows={r['depth_rows']} starters={r['starters']} "
          f"injured_out={r['injured_out']} players_updated={r['updated']}")


if __name__ == "__main__":
    main()
