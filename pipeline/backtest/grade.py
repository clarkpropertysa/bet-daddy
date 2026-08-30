"""Grade emitted signals: closing line value, then settlement P&L.

This closes the loop the whole tiering system depends on. Until a signal is graded it
sits UNVALIDATED forever no matter how good the model is.

Two stages, deliberately separate:

  CLV   computable as soon as a market closes. Compares the entry price to the last
        observed price before close. Needs no settlement, and is far lower variance
        than win rate -- readable after dozens of contracts rather than hundreds.

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
    # last observed price at or before close, per market
    closes = {
        r[0]: (r[1], r[2])
        for r in con.execute(f"""
            with ranked as (
                select market_ticker, yes_ask, result, mins_to_close,
                       row_number() over (
                           partition by market_ticker order by mins_to_close asc
                       ) rn
                from read_parquet('{archive_glob}')
                where mins_to_close >= 0 and yes_ask is not null
            )
            select market_ticker, yes_ask, result from ranked where rn = 1
        """).fetchall()
    }

    graded = settled = skipped_no_close = 0
    now = datetime.now(timezone.utc)

    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        where = 'where s."modelVersion" = %s' if model_version else ""
        cur.execute(
            f'''select s.id, s."marketTicker", s.side, s."marketProb", s."feeCents"
                from "Signal" s
                left join "SignalResult" r on r."signalId" = s.id
                {where} {"and" if model_version else "where"} r."signalId" is null''',
            (model_version,) if model_version else (),
        )
        rows = cur.fetchall()

        for sig_id, ticker, side, entry, fee in rows:
            close = closes.get(ticker)
            if close is None or close[0] is None:
                skipped_no_close += 1
                continue
            close_price, result = close
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
            "skipped_no_close": skipped_no_close}


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
          f"no_close={r['skipped_no_close']}")


if __name__ == "__main__":
    main()
