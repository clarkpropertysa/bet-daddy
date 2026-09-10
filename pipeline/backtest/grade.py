"""Grade emitted signals: closing line value, then settlement P&L.

This closes the loop the whole tiering system depends on. Until a signal is graded it
sits UNVALIDATED forever no matter how good the model is.

Two stages, deliberately separate:

  CLV   computable once the game has KICKED OFF, and not before. Compares the entry price to the
        last observed price before kickoff. Needs no settlement, and is far lower
        variance than win rate -- readable after dozens of contracts rather than
        hundreds.

        NOT "before close". Kalshi's close_time is a settlement deadline two days
        after the game, and these markets stay open THROUGH the game -- they carry
        `can_close_early` and expire when the event occurs. Taking the last price
        before close therefore took a price that had already watched most of the game
        happen, which made CLV a slow restatement of the result and destroyed the one
        property it exists for: that it does not depend on the outcome.

  P&L   requires the settled result, and nets the exact entry fee.

Both read from the Parquet archive, which is the only place price history lives.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import duckdb

from pipeline.backtest.clv import compute_clv_cents, settle_pnl_cents
from pipeline.common import config, db


def _utc(ts):
    """A kickoff as an AWARE UTC datetime.

    Postgres hands back `timestamp without time zone`, stored as UTC. DuckDB reads a
    naive value in its SESSION zone -- America/Chicago on the machine this was found on
    -- so a naive 00:20 kickoff became 05:20 UTC, and "the last price before kickoff"
    was a quote from the fourth quarter: yes 0.00/1.00 on every market. All 3,202
    NE at SEA grades carried that close and a mean CLV of +16.5c. On a CI runner,
    whose zone is UTC, the same code was right by accident, which is why it hid.
    """
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def closing_quotes(con, archive_glob: str, kickoffs: list[tuple]) -> tuple[dict, dict]:
    """(market -> (closing yes_ask, closing yes_bid, result)), (market -> settled result).

    BOTH yes quotes, because the two sides close on different ones. A NO position's
    entry is recorded as `1 - no_ask`, which is the YES BID; comparing it against the
    YES ASK at close scored a flat market as a loss of one full spread on every under --
    median CLV -1.00c on a night of 1c books, which is exactly the tier's pass mark.

    The closing line is the last archived yes quote at or before kickoff; settlement is
    read separately because it only exists after the game.
    """
    closes: dict[str, tuple] = {}
    results: dict[str, str] = {}
    if not kickoffs:
        return closes, results
    # Belt and braces: the column is TIMESTAMPTZ and every value is aware, so the
    # session zone cannot matter -- but pin it anyway.
    con.execute("set TimeZone = 'UTC'")
    con.execute("create or replace table cutoffs "
                "(market_ticker varchar, kickoff timestamptz)")
    con.executemany("insert into cutoffs values (?, ?)",
                    [(t, _utc(k)) for t, k in kickoffs])
    closes = {
        r[0]: (r[1], r[2], r[3])
        for r in con.execute(f"""
            with ranked as (
                select a.market_ticker, a.yes_ask, a.yes_bid, a.result, a.ts,
                       row_number() over (
                           partition by a.market_ticker order by a.ts desc
                       ) rn
                from read_parquet('{archive_glob}', union_by_name=true) a
                join cutoffs c on c.market_ticker = a.market_ticker
                where a.yes_ask is not null and a.ts <= c.kickoff
            )
            select market_ticker, yes_ask, yes_bid, result from ranked where rn = 1
        """).fetchall()
    }
    results = {
        r[0]: r[1]
        for r in con.execute(f"""
            select market_ticker, any_value(result)
            from read_parquet('{archive_glob}', union_by_name=true)
            where result in ('yes','no') group by 1
        """).fetchall()
    }
    return closes, results


def grade(archive_glob: str, model_version: str | None = None) -> dict:
    import psycopg

    con = duckdb.connect()
    graded = settled = skipped_no_close = skipped_no_kickoff = 0
    now = datetime.now(timezone.utc)

    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        where = 'where s."modelVersion" = %s' if model_version else ""
        # ONE DECISION PER MARKET. Every hourly run writes a fresh signal for every
        # open market, so grading them all counted one game as ~20 settled contracts
        # per market -- 3,202 rows from NE at SEA alone, enough for a single evening
        # to carry a family past the 50 and 200 thresholds the tier is built on. The
        # decision that counts is the last one made before kickoff.
        mv = 's."modelVersion" = %s and' if model_version else ""
        cur.execute(
            f'''select distinct on (s."marketTicker")
                       s.id, s."marketTicker", s.side, s."marketProb", s."feeCents",
                       s.kickoff
                from "Signal" s
                where {mv}
                      -- ONLY AFTER KICKOFF, and only decisions made before it. Before
                      -- kickoff there is no closing line yet; grading then recorded
                      -- 5,502 unplayed signals at a mean of -2.96c.
                      s.kickoff is not null and s.kickoff < now()
                  and s."runTs" < s.kickoff
                  and not exists (
                      select 1 from "SignalResult" r
                      join "Signal" s2 on s2.id = r."signalId"
                      where s2."marketTicker" = s."marketTicker")
                order by s."marketTicker", s."runTs" desc''',
            (model_version,) if model_version else (),
        )
        rows = cur.fetchall()

        # THE CLOSING LINE IS THE LAST PRICE BEFORE KICKOFF, per market. Built here
        # rather than as one archive-wide query because the cutoff differs by fixture:
        # a Thursday game and a Sunday game close at different times, and Kalshi's own
        # close_time is two days after either.
        kickoffs = [(t, k) for _i, t, _s, _p, _f, k in rows if k is not None]
        closes, results = closing_quotes(con, archive_glob, kickoffs)

        for sig_id, ticker, side, entry, fee, kickoff in rows:
            if kickoff is None:
                # Without a kickoff there is no closing line to measure against, and
                # guessing one from close_time is the bug this replaced.
                skipped_no_kickoff += 1
                continue
            close = closes.get(ticker)
            if close is None or close[0] is None:
                skipped_no_close += 1
                continue
            close_ask, close_bid, _pre_result = close
            # Bid-consistent on both sides: a YES entry is an ask and closes on the ask;
            # a NO entry is stored as 1 - no_ask, i.e. the yes BID, and closes on the
            # yes bid. Mixing them charged every under a phantom spread.
            if side == "no":
                if close_bid is None:
                    skipped_no_close += 1
                    continue
                close_price = close_bid
            else:
                close_price = close_ask
            result = results.get(ticker)
            # UNITS. compute_clv_cents wants BOTH prices as YES prices and flips the
            # sign itself for a NO position. Signal.marketProb stores the price of
            # the side actually taken, so a NO signal holds (1 - yes_ask). Passing it
            # straight through compares a NO entry against a YES close and produces
            # nonsense -- it showed as -50c mean CLV on NO signals against +1.5c on
            # YES, which looked like a model failure and was an arithmetic one.
            yes_entry = entry if side == "yes" else (1 - entry)
            clv = compute_clv_cents(yes_entry, close_price, side)

            pnl = None
            if result in ("yes", "no"):
                # settle_pnl_cents also takes the YES price and derives the NO cost
                # as its complement.
                pnl = settle_pnl_cents(yes_entry, side, result, fee)
                settled += 1

            cur.execute(
                '''insert into "SignalResult"
                     ("signalId", "closingPrice", "clvCents", "settledResult",
                      "pnlIfBet", "gradedTs")
                   values (%s,%s,%s,%s,%s,%s)
                   on conflict ("signalId") do update
                     set "closingPrice" = excluded."closingPrice",
                         "clvCents" = excluded."clvCents",
                         "settledResult" = excluded."settledResult",
                         "pnlIfBet" = excluded."pnlIfBet",
                         "gradedTs" = excluded."gradedTs"''',
                (sig_id, close_price, clv, result if result in ("yes","no") else None,
                 pnl, now),
            )
            graded += 1

    return {"candidates": len(rows), "graded": graded, "settled": settled,
            "skipped_no_close": skipped_no_close,
            "skipped_no_kickoff": skipped_no_kickoff}


def main():
    ap = argparse.ArgumentParser(description="Grade signals on CLV and settlement")
    ap.add_argument("--archive", default="data/archive/market_snapshots/**/*.parquet")
    ap.add_argument("--model-version", default=None)
    a = ap.parse_args()
    with db.track("grade") as run:
        r = grade(a.archive, a.model_version)
        run["rows"] = r["graded"]
        run["meta"] = r
    print(f"candidates={r['candidates']} graded={r['graded']} settled={r['settled']} "
          f"no_close={r['skipped_no_close']} "
          f"no_kickoff={r['skipped_no_kickoff']}")
    if r["candidates"] and not r["graded"]:
        print("  NOTE: candidates were found and none could be graded. Every one either "
              "lacks a kickoff or has no archived price before it -- check that the "
              "archiver ran during the window before those games.")
    if r["skipped_no_close"]:
        print(f"  WARNING: {r['skipped_no_close']} signals have a kickoff but NO "
              "archived price before it. CLV cannot be computed for them and they will "
              "stay unvalidated -- the archiver was not running in time.")


if __name__ == "__main__":
    main()
