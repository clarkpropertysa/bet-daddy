"""The closing line must be the last quote before kickoff whatever zone DuckDB is in.

Postgres returns kickoff as a naive timestamp stored in UTC. DuckDB reads a naive value
in its SESSION zone, so on a machine in America/Chicago a 00:20 kickoff became 05:20 UTC
and the grader took a fourth-quarter quote as the close: yes 0.00/1.00 on every market,
a mean CLV of +16.5c over 3,202 grades from a single game. CI runs in UTC, where the same
code was right by accident -- so these tests force a non-UTC session on purpose.
"""
import datetime as dt

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.backtest.clv import closing_price
from pipeline.backtest.grade import _utc, closing_quotes

KICK_NAIVE = dt.datetime(2026, 9, 10, 0, 20)            # what Postgres hands back
KICK_UTC = KICK_NAIVE.replace(tzinfo=dt.timezone.utc)
T = "KXNFLPASSYDS-26SEP09NESEA-NEDMAYE10-175"


def _archive(tmp_path):
    rows = [
        # genuine pre-game quotes
        {"market_ticker": T, "ts": KICK_UTC - dt.timedelta(hours=3),
         "mins_to_close": 3060, "yes_bid": 0.80, "yes_ask": 0.83, "result": None},
        {"market_ticker": T, "ts": KICK_UTC - dt.timedelta(minutes=20),
         "mins_to_close": 2900, "yes_bid": 0.82, "yes_ask": 0.83, "result": None},
        # in-game, inside the five hours a Chicago session would wrongly admit
        {"market_ticker": T, "ts": KICK_UTC + dt.timedelta(hours=2),
         "mins_to_close": 2760, "yes_bid": 0.37, "yes_ask": 0.38, "result": None},
        {"market_ticker": T, "ts": KICK_UTC + dt.timedelta(hours=4, minutes=40),
         "mins_to_close": 2600, "yes_bid": 0.00, "yes_ask": 1.00, "result": None},
        # settlement, days later
        {"market_ticker": T, "ts": KICK_UTC + dt.timedelta(days=2),
         "mins_to_close": 0, "yes_bid": 0.99, "yes_ask": 1.00, "result": "yes"},
    ]
    tbl = pa.Table.from_pylist(rows, schema=pa.schema([
        ("market_ticker", pa.string()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("mins_to_close", pa.int64()),
        ("yes_bid", pa.float64()),
        ("yes_ask", pa.float64()),
        ("result", pa.string()),
    ]))
    path = tmp_path / "snap.parquet"
    pq.write_table(tbl, path)
    return str(path)


def test_utc_attaches_the_zone_postgres_stores_in():
    assert _utc(KICK_NAIVE) == KICK_UTC
    assert _utc(KICK_NAIVE).tzinfo is not None
    assert _utc(None) is None
    chicago = dt.timezone(dt.timedelta(hours=-5))
    assert _utc(dt.datetime(2026, 9, 9, 19, 20, tzinfo=chicago)) == KICK_UTC


@pytest.mark.parametrize("zone", ["America/Chicago", "Asia/Tokyo", "UTC"])
def test_the_close_is_pre_kickoff_in_any_session_zone(tmp_path, zone):
    con = duckdb.connect()
    con.execute(f"set TimeZone = '{zone}'")
    closes, results = closing_quotes(con, _archive(tmp_path), [(T, KICK_NAIVE)])
    ask, bid, _ = closes[T]
    assert float(bid) == pytest.approx(0.82)
    assert float(ask) == pytest.approx(0.83), (
        f"in a {zone} session the close must be the 0.83 quote from 20 minutes before "
        f"kickoff, not an in-game price"
    )
    assert results[T] == "yes"


def test_the_in_game_price_the_bug_used_is_what_a_naive_cutoff_selects(tmp_path):
    """Pin the failure itself, so the difference stays visible: a NAIVE cutoff column
    in a Chicago session reaches 4h40m past kickoff and returns the 1.00 ask."""
    con = duckdb.connect()
    con.execute("set TimeZone = 'America/Chicago'")
    con.execute("create table cut (k timestamp)")
    con.execute("insert into cut values (?)", [KICK_NAIVE])
    r = con.execute(f"""
        select a.yes_ask from read_parquet('{_archive(tmp_path)}') a, cut
        where a.ts <= cut.k order by a.ts desc limit 1""").fetchone()
    assert float(r[0]) == pytest.approx(1.00)


def test_clv_closing_price_treats_a_naive_kickoff_as_utc(tmp_path):
    """clv.closing_price had the identical latent bug; its earlier test passed only
    because it handed in an aware datetime."""
    got = closing_price(_archive(tmp_path), T, kickoff=KICK_NAIVE)
    assert got is not None
    assert float(got.yes_ask) == pytest.approx(0.83)


def test_a_flat_market_scores_zero_clv_on_either_side():
    """No movement must mean no CLV, for an under as much as an over.

    A NO entry is stored as 1 - no_ask, which on Kalshi is the YES BID. Closing it on
    the YES ASK charged every under one full spread for doing nothing: median CLV came
    out at exactly -1.00c on a night of 1c books, which is the tier's pass mark.
    """
    from decimal import Decimal

    from pipeline.backtest.clv import compute_clv_cents

    yes_bid, yes_ask = Decimal("0.82"), Decimal("0.83")
    no_ask = 1 - yes_bid                      # 0.18, what an under is bought at

    # over: entered on the ask, closes on the ask
    assert compute_clv_cents(yes_ask, yes_ask, "yes") == 0
    # under: entered at 1 - no_ask (= yes bid), must close on the yes BID
    assert compute_clv_cents(1 - no_ask, yes_bid, "no") == 0
    # the old pairing, pinned so the difference stays visible
    assert compute_clv_cents(1 - no_ask, yes_ask, "no") == Decimal("-1")
