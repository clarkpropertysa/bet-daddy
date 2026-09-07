"""The live/settled price split.

The board was empty for the whole life of the project because ONE query served both
backtesting and live serving. The settled path filters on `result in ('yes','no')`,
an open market has no result yet, and so the board could only ever show games that
had already finished. These tests pin the two paths apart.
"""
import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.model.project import (
    _open_prices,
    _settled_prices,
    open_market_census,
)

NOW = dt.datetime.now(dt.timezone.utc)


def _write(tmp_path: Path, rows: list[dict]) -> str:
    """A snapshot archive shaped like the real one."""
    tbl = pa.Table.from_pylist(rows, schema=pa.schema([
        ("market_ticker", pa.string()),
        ("series_ticker", pa.string()),
        ("market_type", pa.string()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("yes_ask", pa.float64()),
        ("no_ask", pa.float64()),
        # Liquidity: the board needs to know whether there is anyone to trade with.
        ("yes_bid", pa.float64()),
        ("volume", pa.float64()),
        ("open_interest", pa.float64()),
        ("strike", pa.float64()),
        ("close_time", pa.timestamp("us", tz="UTC")),
        ("mins_to_close", pa.int64()),
        ("result", pa.string()),
    ]))
    p = tmp_path / "snap.parquet"
    pq.write_table(tbl, p)
    return str(p)


def _row(ticker, *, ask, result, close_in_mins, age_mins, mins_to_close=None,
         no_ask=None, yes_bid=None, volume=0.0, open_interest=0.0):
    close = NOW + dt.timedelta(minutes=close_in_mins)
    ts = NOW - dt.timedelta(minutes=age_mins)
    return {
        "market_ticker": ticker, "series_ticker": "KXNFLPASSYDS",
        "market_type": "pass_yds", "ts": ts, "yes_ask": ask,
        # The REAL no-side ask. Inferring 1 - yes_ask is fiction on a one-sided book.
        "no_ask": no_ask if no_ask is not None else (None if ask is None else 1.0 - ask),
        "yes_bid": yes_bid if yes_bid is not None else (
            None if ask is None else max(ask - 0.02, 0.0)),
        "volume": volume,
        "open_interest": open_interest,
        "strike": 250.0,
        "close_time": close, "mins_to_close": mins_to_close if mins_to_close
        is not None else int((close - ts).total_seconds() // 60),
        "result": result,
    }


def test_open_market_is_invisible_to_the_settled_selector(tmp_path):
    """The original bug, stated as a test. An unsettled market has no result, so the
    backtest selector cannot see it -- which is correct FOR BACKTESTING and was
    catastrophic for the board."""
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=0.42, result=None, close_in_mins=600, age_mins=5),
    ])
    assert _settled_prices(glob, 60) == []
    assert len(_open_prices(glob, 180)) == 1


def test_settled_market_is_invisible_to_the_live_selector(tmp_path):
    """And the reverse: a finished game must never appear on a live board."""
    glob = _write(tmp_path, [
        _row("DONE-1", ask=0.42, result="yes", close_in_mins=-600, age_mins=700),
    ])
    assert _open_prices(glob, 100_000) == []
    assert len(_settled_prices(glob, 60)) == 1


def test_live_selector_takes_the_freshest_quote(tmp_path):
    """Not the one nearest a horizon -- the newest one there is."""
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=0.30, result=None, close_in_mins=600, age_mins=120),
        _row("OPEN-1", ask=0.55, result=None, close_in_mins=600, age_mins=3),
    ])
    got = _open_prices(glob, 180)
    assert len(got) == 1
    assert got[0]["yes_ask"] == pytest.approx(0.55)


def test_stale_quote_is_refused_rather_than_shown_as_current(tmp_path):
    """If the archiver stops, the board must go blank, not keep serving an old price
    as though it were the market right now."""
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=0.42, result=None, close_in_mins=600, age_mins=400),
    ])
    assert _open_prices(glob, 180) == []
    assert len(_open_prices(glob, 500)) == 1


def test_unquoted_market_produces_no_price(tmp_path):
    """A listed-but-unquoted market is the actual state of every Week 1 prop well
    before kickoff. It must yield nothing rather than a fabricated price."""
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=None, result=None, close_in_mins=600, age_mins=5),
    ])
    assert _open_prices(glob, 180) == []


def test_mins_to_close_is_recomputed_not_read(tmp_path):
    """The archived value was true when the snapshot was taken and is stale by
    exactly the snapshot's age."""
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=0.42, result=None, close_in_mins=600, age_mins=90,
             mins_to_close=999_999),
    ])
    got = _open_prices(glob, 180)[0]
    assert got["mins_to_close"] != 999_999
    assert 590 <= got["mins_to_close"] <= 601


def test_price_ts_is_carried_so_the_board_can_show_quote_age(tmp_path):
    glob = _write(tmp_path, [
        _row("OPEN-1", ask=0.42, result=None, close_in_mins=600, age_mins=7),
    ])
    assert _open_prices(glob, 180)[0]["price_ts"] is not None


def test_census_separates_unlisted_unquoted_and_stale(tmp_path):
    """Three causes of an empty board that look identical to a user and need
    different responses: wait, wait longer, or go fix the archiver."""
    glob = _write(tmp_path, [
        _row("QUOTED-FRESH", ask=0.42, result=None, close_in_mins=600, age_mins=5),
        _row("QUOTED-STALE", ask=0.42, result=None, close_in_mins=600, age_mins=900),
        _row("UNQUOTED", ask=None, result=None, close_in_mins=600, age_mins=5),
        _row("FINISHED", ask=0.42, result="no", close_in_mins=-600, age_mins=700),
    ])
    c = open_market_census(glob, 180)
    assert c["listed"] == 3      # the settled one is not upcoming
    assert c["quoted"] == 2      # the unquoted one has no price
    assert c["fresh"] == 1       # only one is inside the freshness limit


def test_extreme_asks_are_excluded_from_live_too(tmp_path):
    """A 0c ask is an empty book reported as a number, on a live market as much as a
    settled one."""
    glob = _write(tmp_path, [
        _row("ZERO", ask=0.0, result=None, close_in_mins=600, age_mins=5),
        _row("ONE", ask=1.0, result=None, close_in_mins=600, age_mins=5),
    ])
    assert _open_prices(glob, 180) == []


def test_the_real_no_side_ask_is_carried_not_inferred(tmp_path):
    """compute_edge falls back to `1 - yes_ask` for the no side, which is fiction on a
    one-sided book.

    Rhamondre Stevenson 8+ receptions quoted yes_ask 0.97 with no_ask 1.0000. The
    inferred no price of 0.03 implied a 97-cent edge on a contract that could not be
    bought at any price -- it would have been the top row of the board.
    """
    glob = _write(tmp_path, [
        _row("ONE-SIDED", ask=0.97, no_ask=1.0, result=None,
             close_in_mins=600, age_mins=5),
    ])
    got = _open_prices(glob, 180)
    assert len(got) == 1
    assert got[0]["no_ask"] == pytest.approx(1.0), (
        "the real no-side ask must survive to the edge calculation; inferring it "
        "manufactures an edge on an unexecutable trade"
    )


def test_an_archive_without_the_column_still_loads(tmp_path):
    """Snapshots taken before no_ask existed must not break the selector."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    old = pa.Table.from_pylist(
        [{"market_ticker": "OLD-1", "series_ticker": "S", "market_type": "pass_yds",
          "ts": NOW - dt.timedelta(minutes=5), "yes_ask": 0.42, "strike": 250.0,
          "close_time": NOW + dt.timedelta(minutes=600), "mins_to_close": 600,
          "result": None}],
        schema=pa.schema([
            ("market_ticker", pa.string()), ("series_ticker", pa.string()),
            ("market_type", pa.string()), ("ts", pa.timestamp("us", tz="UTC")),
            ("yes_ask", pa.float64()), ("strike", pa.float64()),
            ("close_time", pa.timestamp("us", tz="UTC")),
            ("mins_to_close", pa.int64()), ("result", pa.string()),
        ]),
    )
    d = tmp_path / "mixed"
    d.mkdir()
    pq.write_table(old, d / "old.parquet")
    _write(d, [_row("NEW-1", ask=0.5, result=None, close_in_mins=600, age_mins=5)])
    got = _open_prices(str(d / "*.parquet"), 180)
    assert len(got) == 2
    assert any(r["no_ask"] is None for r in got)
