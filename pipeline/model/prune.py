"""Keep the Signal table to the rows something still reads.

Every live run writes one Signal per quoted market, and each carries the full rationale
as JSON -- about 2.3 KB. Runs land several times an hour on a busy day, so one game's
ladder was stored twenty times over, and by Week 1 the table was 406 MB of a 489 MB
database against Neon's 512 MB ceiling. That ceiling is not academic: project-live began
failing with `DiskFull: could not extend file because project size limit (512 MB) has
been exceeded`, and the board stopped updating. Nothing reads a superseded run:

  * the board, Top Picks, the slate and the player pages -- the NEWEST run only
    (web/src/lib/queries.ts scopes every one of them to max(runTs));
  * the grader -- per market, the LAST signal written before kickoff
    (pipeline/backtest/grade.py), until it has a SignalResult;
  * the Track Record and tier promotion -- rows that HAVE a SignalResult;
  * settled mode's dedupe -- that the ticker appears at all (project.py), so a market
    already emitted is not emitted again every day.

So per market this keeps the newest pre-kickoff signal, the first post-kickoff one
(the settled-mode marker), anything graded, and everything in the board's run. Every
ticker therefore keeps at least one row.

ONE MARKET AT A TIME, RESUMABLE, AND NOTHING SCANS THE WHOLE TABLE. Three earlier
designs died on this database: a single transaction plus a `not exists` sweep over
`Projection`; a batched delete whose per-batch window query still read every row; and a
per-market version that still deleted projections inline. A compute sitting at its
storage ceiling drops connections mid-statement -- including on a 67-row indexed SELECT
-- so the rule is applied per market, committed per batch, and the connection is
re-established whenever it dies. Each run resumes where the last stopped.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from pipeline.common import config, db

#: Ids per DELETE. Small enough that no statement is long enough to be dropped.
BATCH = 500

# Portable between Postgres and DuckDB so the selection is tested without a server.
# `{now}` is the driver's placeholder: a bound parameter keeps the test deterministic.
# Kept as the specification of what "superseded" means -- tests/test_prune.py runs it --
# while `doomed_for_market` below applies the same rule one market at a time.
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


def doomed_sql(placeholder: str) -> str:
    return _DOOMED.format(now=placeholder)


def doomed_for_market(rows, board_ts, graded) -> list:
    """The same rule as `_DOOMED`, decided in Python for one market's rows.

    `rows` is (id, projectionId, runTs, kickoff). Returns (id, projectionId) to delete.
    """
    pre = [r for r in rows if r[3] is None or r[2] < r[3]]
    post = [r for r in rows if not (r[3] is None or r[2] < r[3])]
    keep = set()
    if pre:
        keep.add(max(pre, key=lambda r: r[2])[0])       # the grader's row
    if post:
        keep.add(min(post, key=lambda r: r[2])[0])      # settled mode's marker
    return [(r[0], r[1]) for r in rows
            if r[0] not in keep and r[2] != board_ts and r[0] not in graded]


def _connect():
    import psycopg

    # The DIRECT endpoint, not the pooler: these are many small statements in their own
    # transactions, and the pooled host dropped long ones mid-flight. Keepalives because
    # the first failure of all was "SSL SYSCALL error: Operation timed out".
    url = config.DATABASE_URL.replace("-pooler", "")
    return psycopg.connect(url, connect_timeout=30, keepalives=1, keepalives_idle=20,
                           keepalives_interval=10, keepalives_count=5)


def reconnect(conn, attempts: int = 8):
    """Return a live connection, replacing one the compute has dropped.

    A Neon project at its size limit restarts under sustained load -- measured here at
    roughly one restart per thousand rows deleted. Reconnecting is what turns that from
    a failed run into a slower one.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        return conn
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
    last = None
    for attempt in range(attempts):
        try:
            return _connect()
        except Exception as e:                       # compute still coming back up
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not reconnect: {last!r}")


def prune(conn, now: datetime, dry_run: bool = False, batch: int = BATCH,
          progress=None) -> dict:
    """Delete superseded signals. Returns the counts. Safe to run again after a drop."""
    with conn.cursor() as cur:
        cur.execute('select max("runTs") from "Signal" where kickoff > %s', (now,))
        board_ts = cur.fetchone()[0]
        cur.execute('select "signalId" from "SignalResult"')
        graded = {r[0] for r in cur.fetchall()}
        cur.execute('select distinct "marketTicker" from "Signal"')
        tickers = [r[0] for r in cur.fetchall()]
    conn.commit()

    signals = markets = 0
    for ticker in tickers:
        for attempt in range(3):
            try:
                conn = reconnect(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        'select id, "projectionId", "runTs", kickoff from "Signal" '
                        'where "marketTicker" = %s', (ticker,))
                    doomed = doomed_for_market(cur.fetchall(), board_ts, graded)
                    if dry_run:
                        signals += len(doomed)
                    else:
                        for i in range(0, len(doomed), batch):
                            chunk = doomed[i:i + batch]
                            cur.execute('delete from "Signal" where id = any(%s)',
                                        ([c[0] for c in chunk],))
                            signals += cur.rowcount
                            conn.commit()
                conn.commit()
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"  {type(e).__name__} on {ticker}, retrying", flush=True)
                time.sleep(3)
        markets += 1
        if progress and markets % 100 == 0:
            progress(markets, len(tickers), signals, 0)
    return {"signals": signals, "markets": markets, "conn": conn}


#: `Signal."projectionId"` has no index, and the foreign key to `Projection` means
#: Postgres proves no signal references a projection before deleting it -- one
#: sequential scan of a 406 MB table PER ROW. That is what closed the connection on
#: three separate designs. Signals go first and are vacuumed, so the table this index
#: covers is small by the time it is built, and the check becomes a lookup.
PROJECTION_FK_INDEX = (
    'create index if not exists "Signal_projectionId_idx" on "Signal" ("projectionId")'
)


def prune_projections(conn, batch: int = BATCH, progress=None) -> int:
    """Delete projections no signal points to. Requires PROJECTION_FK_INDEX."""
    deleted = 0
    conn = reconnect(conn)
    with conn.cursor() as cur:
        cur.execute(PROJECTION_FK_INDEX)
    conn.commit()
    while True:
        conn = reconnect(conn)
        with conn.cursor() as cur:
            cur.execute(
                'delete from "Projection" where id in ('
                '  select p.id from "Projection" p'
                '  where not exists (select 1 from "Signal" s'
                '                    where s."projectionId" = p.id)'
                '  limit %s)', (batch,))
            n = cur.rowcount
        conn.commit()
        deleted += n
        if progress:
            progress(deleted)
        if not n:
            return deleted


def _size() -> str:
    with _connect() as c, c.cursor() as cur:
        cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
        return cur.fetchone()[0]


def _vacuum(table: str, full: bool) -> None:
    # Its own connection and autocommit: VACUUM cannot run inside a transaction, and
    # the space must come back before the next phase needs room for an index.
    with _connect() as ac:
        ac.autocommit = True
        verb = "vacuum (full, analyze)" if full else "vacuum (analyze)"
        print(f"  {verb} {table}", flush=True)
        ac.execute(f"{verb} {table}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--signals-only", action="store_true",
                    help="skip the projection phase and its vacuum")
    ap.add_argument("--full", action="store_true",
                    help="VACUUM FULL: return the space to Neon. Takes an exclusive "
                         "lock and rewrites the table; routine runs use plain VACUUM, "
                         "which lets Postgres reuse the space so it stops growing.")
    a = ap.parse_args()

    def say(m, total, s, p):
        print(f"  {m}/{total} markets, {s:,} signals", flush=True)

    with db.track("prune_signals") as run:
        before = _size()
        conn = _connect()
        got = prune(conn, datetime.now(timezone.utc), dry_run=a.dry_run,
                    batch=a.batch, progress=say)
        conn = got.pop("conn")
        run["rows"] = got["signals"]
        if not a.dry_run:
            # SIGNALS FIRST, AND VACUUMED BEFORE THE PROJECTIONS ARE TOUCHED. Deleting
            # a projection costs a full scan of Signal until the table is small and the
            # foreign key column is indexed; this ordering is what lets phase two run.
            _vacuum('"Signal"', a.full)
            if not a.signals_only:
                got["projections"] = prune_projections(
                    conn, batch=a.batch,
                    progress=lambda n: print(f"  {n:,} projections", flush=True))
                _vacuum('"Projection"', a.full)
        try:
            conn.close()
        except Exception:
            pass
        after = _size()
        run["meta"].update(got)
        run["meta"].update({"size_before": before, "size_after": after})
        print(f"signals={got['signals']} projections={got.get('projections')} "
              f"markets={got['markets']} db_size {before} -> {after}"
              f"{' (dry run)' if a.dry_run else ''}")


if __name__ == "__main__":
    main()
