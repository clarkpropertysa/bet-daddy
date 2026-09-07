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


def grade(archive_glob: str, model_version: str | None = None) -> dict:
    import psycopg

    con = duckdb.connect()
    graded = settled = skipped_no_close = skipped_no_kickoff = 0
    now = datetime.now(timezone.utc)

    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        where = 'where s."modelVersion" = %s' if model_version else ""
        cur.execute(
            f'''select s.id, s."marketTicker", s.side, s."marketProb", s."feeCents",
                       s.kickoff
                from "Signal" s
                left join "SignalResult" r on r."signalId" = s.id
                {where} {"and" if model_version else "where"} r."signalId" is null
                  -- ONLY AFTER KICKOFF. Before it there is no closing line yet: the
                  -- last snapshot is simply the current price, and grading against it
                  -- records a CLV of roughly zero for a bet nobody has finished
                  -- making. It graded 5,502 unplayed Week 1 signals at a mean of
                  -- -2.96c, which would have gone straight into the tier maths as
                  -- evidence the model was losing.
                  and s.kickoff is not null and s.kickoff < now()''',
            (model_version,) if model_version else (),
        )
        rows = cur.fetchall()

        # THE CLOSING LINE IS THE LAST PRICE BEFORE KICKOFF, per market. Built here
        # rather than as one archive-wide query because the cutoff differs by fixture:
        # a Thursday game and a Sunday game close at different times, and Kalshi's own
        # close_time is two days after either.
        kickoffs = [(t, k) for _i, t, _s, _p, _f, k in rows if k is not None]
        closes: dict[str, tuple] = {}
        if kickoffs:
            con.execute("create or replace table cutoffs (market_ticker varchar, "
                        "kickoff timestamp)")
            con.executemany("insert into cutoffs values (?, ?)", kickoffs)
            closes = {
                r[0]: (r[1], r[2])
                for r in con.execute(f"""
                    with ranked as (
                        select a.market_ticker, a.yes_ask, a.result, a.ts,
                               row_number() over (
                                   partition by a.market_ticker order by a.ts desc
                               ) rn
                        from read_parquet('{archive_glob}', union_by_name=true) a
                        join cutoffs c on c.market_ticker = a.market_ticker
                        where a.yes_ask is not null and a.ts <= c.kickoff
                    )
                    select market_ticker, yes_ask, result from ranked where rn = 1
                """).fetchall()
            }
            # Settlement is read separately: it is only known AFTER the game, so it
            # cannot come from a pre-kickoff snapshot.
            results = {
                r[0]: r[1]
                for r in con.execute(f"""
                    select market_ticker, any_value(result)
                    from read_parquet('{archive_glob}', union_by_name=true)
                    where result in ('yes','no') group by 1
                """).fetchall()
            }
        else:
            results = {}

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
            close_price, _pre_result = close
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
