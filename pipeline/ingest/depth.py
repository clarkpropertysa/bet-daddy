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
from pipeline.features.starters import (
    OUT_STATUSES,
    STARTER_DEPTH,
    latest_depth,
    resolve_starters,
)

# STARTER_DEPTH and OUT_STATUSES live in features/starters.py -- the single source
# of truth, shared with the projection job so the two cannot disagree about who is
# starting.


def sync_depth(depth_path: str, injuries_path: str | None = None) -> dict:
    """Write depth standing and starter flags into Player."""
    import psycopg

    rows = latest_depth(depth_path)
    starters = resolve_starters(depth_path, injuries_path)

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
                (pos, rank, st is not None, st.promoted_for if st else None, gsis),
            )
            updated += cur.rowcount
    return {"depth_rows": len(rows), "starters": len(starters),
            "injured_out": len(starters and [s for s in starters.values() if s.promoted_for]),
            "updated": updated}


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
