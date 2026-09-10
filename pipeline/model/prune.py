"""Keep the Signal table to the rows something still reads.

Every live run writes one Signal per quoted market, and each carries the full rationale
as JSON -- about 2.3 KB. Runs land several times an hour on a busy day, so one game's
ladder was stored twenty times over, and by Week 1 the table was 352 MB of a 427 MB
database on a plan capped at 512 MB. Nothing reads a superseded run. The readers are:

  * the board, Top Picks, the slate and the player pages -- the NEWEST run only
    (web/src/lib/queries.ts scopes every one of them to max(runTs));
  * the grader -- per market, the LAST signal written before kickoff
    (pipeline/backtest/grade.py), until it has a SignalResult;
  * the Track Record and tier promotion -- rows that HAVE a SignalResult;
  * settled mode's dedupe -- that the ticker appears at all (project.py), so a market
    already emitted is not emitted again every day.

So per market this keeps the newest pre-kickoff signal, the first post-kickoff one
(the settled-mode marker), anything graded, and everything in the board's run. Every
ticker therefore keeps at least one row. Projections are read only through a Signal
join, so a projection no signal points to is removed with it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from pipeline.common import config, db

# Portable between Postgres and DuckDB so the selection is tested without a server.
# `{now}` is the driver's placeholder: a bound parameter keeps the test deterministic.
_DOOMED = """
    with ranked as (
        select s.id, s."runTs",
               coalesce(s."runTs" < s.kickoff, true) as pre,
               row_number() over (
                   partition by s."marketTicker", coalesce(s."runTs" < s.kickoff, true)
                   order by s."runTs" desc) as newest_first,
               row_number() over (
                   partition by s."marketTicker", coalesce(s."runTs" < s.kickoff, true)
                   order by s."runTs" asc) as oldest_first
        from "Signal" s
    ),
    board as (select max(s."runTs") as ts from "Signal" s where s.kickoff > {now})
    select r.id from ranked r
    where not (r.pre and r.newest_first = 1)
      and not (not r.pre and r.oldest_first = 1)
      and r."runTs" is distinct from (select ts from board)
      and not exists (select 1 from "SignalResult" x where x."signalId" = r.id)
"""

_ORPHAN_PROJECTIONS = """
    delete from "Projection" p
    where not exists (select 1 from "Signal" s where s."projectionId" = p.id)
"""


def doomed_sql(placeholder: str) -> str:
    return _DOOMED.format(now=placeholder)


def prune(conn, now: datetime, dry_run: bool = False) -> dict:
    """Delete superseded signals and their projections. Returns the counts."""
    with conn.cursor() as cur:
        if dry_run:
            cur.execute(f"select count(*) from ({doomed_sql('%s')}) d", (now,))
            return {"signals": cur.fetchone()[0], "projections": None}
        cur.execute(f'delete from "Signal" where id in ({doomed_sql("%s")})', (now,))
        signals = cur.rowcount
        cur.execute(_ORPHAN_PROJECTIONS)
        projections = cur.rowcount
    conn.commit()
    return {"signals": signals, "projections": projections}


def _size(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
        return cur.fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    ap.add_argument("--full", action="store_true",
                    help="VACUUM FULL: return the space to Neon. Takes an exclusive "
                         "lock for its duration; routine runs use plain VACUUM, which "
                         "lets Postgres reuse the space so the table stops growing.")
    a = ap.parse_args()

    import psycopg

    with db.track("prune_signals") as run, psycopg.connect(config.DATABASE_URL) as conn:
        before = _size(conn)
        got = prune(conn, datetime.now(timezone.utc), dry_run=a.dry_run)
        run["rows"] = got["signals"]
        run["meta"].update(got)
        if not a.dry_run:
            with psycopg.connect(config.DATABASE_URL, autocommit=True) as ac:
                verb = "vacuum (full, analyze)" if a.full else "vacuum (analyze)"
                for t in ('"Signal"', '"Projection"'):
                    ac.execute(f"{verb} {t}")
        after = _size(conn)
        run["meta"].update({"size_before": before, "size_after": after})
        print(f"signals={got['signals']} projections={got['projections']} "
              f"db_size {before} -> {after}{' (dry run)' if a.dry_run else ''}")


if __name__ == "__main__":
    main()
