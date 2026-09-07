"""The closing line is kickoff, not Kalshi's settlement deadline.

`close_time` sits two days after the game and these markets carry `can_close_early`:
they stay open THROUGH the game and expire when the event occurs. Taking the last price
before close therefore took a price that had already watched the outcome, which would
have made CLV a slow restatement of settlement -- forfeiting the one property the metric
exists for, that it is independent of the result and readable after dozens of contracts.
"""
import datetime as dt
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.backtest.clv import closing_price

KICK = dt.datetime(2026, 9, 13, 17, 0, tzinfo=dt.timezone.utc)


def _archive(tmp_path: Path) -> str:
    rows = [
        # well before kickoff: a genuine market price
        {"market_ticker": "M", "ts": KICK - dt.timedelta(hours=6),
         "mins_to_close": 3240, "yes_bid": 0.40, "yes_ask": 0.44, "result": None},
        # the closing line: last quote before the game starts
        {"market_ticker": "M", "ts": KICK - dt.timedelta(minutes=5),
         "mins_to_close": 2885, "yes_bid": 0.46, "yes_ask": 0.50, "result": None},
        # DURING the game, price collapsing as the outcome becomes clear
        {"market_ticker": "M", "ts": KICK + dt.timedelta(hours=2),
         "mins_to_close": 2760, "yes_bid": 0.02, "yes_ask": 0.04, "result": None},
        # after the game, effectively settled but still before close_time
        {"market_ticker": "M", "ts": KICK + dt.timedelta(hours=20),
         "mins_to_close": 1680, "yes_bid": 0.00, "yes_ask": 0.01, "result": None},
    ]
    tbl = pa.Table.from_pylist(rows, schema=pa.schema([
        ("market_ticker", pa.string()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("mins_to_close", pa.int64()),
        ("yes_bid", pa.float64()),
        ("yes_ask", pa.float64()),
        ("result", pa.string()),
    ]))
    p = tmp_path / "snap.parquet"
    pq.write_table(tbl, p)
    return str(p)


def test_the_closing_line_is_the_last_price_before_kickoff(tmp_path):
    got = closing_price(_archive(tmp_path), "M", kickoff=KICK)
    assert got is not None
    assert got.yes_ask == pytest.approx(0.50)
    assert got.ts <= KICK


def test_without_a_kickoff_it_picks_a_price_that_has_seen_the_game(tmp_path):
    """The old behaviour, kept only as a fallback and pinned here so the difference is
    visible: it returns 0.01, a price that already knows the answer."""
    got = closing_price(_archive(tmp_path), "M")
    assert got is not None
    assert got.yes_ask == pytest.approx(0.01)
    assert got.ts > KICK


def test_a_market_with_no_pre_kickoff_snapshot_yields_nothing(tmp_path):
    """Better to grade nothing than to grade against an in-game price."""
    late = KICK - dt.timedelta(days=3)
    assert closing_price(_archive(tmp_path), "M", kickoff=late) is None
