"""CLV lookups against a real Parquet archive written in the pipeline's own format."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.backtest.clv import closing_price, price_at
from pipeline.ingest.kalshi_archiver import SCHEMA


@pytest.fixture
def archive(tmp_path):
    """Snapshots of one market marching from T-360 down to T-0."""
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    rows = []
    for mins, bid, ask in [
        (360, "0.30", "0.34"), (180, "0.33", "0.36"), (90, "0.36", "0.39"),
        (60, "0.38", "0.41"), (30, "0.41", "0.44"), (5, "0.45", "0.48"),
    ]:
        rows.append({
            "market_ticker": "KXNFLRECYDS-TEST-PLAYER1-50",
            "series_ticker": "KXNFLRECYDS", "event_ticker": "TEST",
            "sport": "nfl", "market_type": "rec_yds",
            "ts": now - timedelta(minutes=mins),
            # Decimal, not str: the archiver writes Decimals and the schema is
            # decimal128. Money never becomes a float anywhere in this pipeline.
            "yes_bid": Decimal(bid), "yes_ask": Decimal(ask),
            "last_price": Decimal(bid),
            "volume": Decimal("100"), "open_interest": Decimal("500"),
            "strike": 50.0,
            "status": "active", "close_time": now,
            "mins_to_close": mins, "result": None, "orderbook": None,
            "source": "test",
        })
    d = tmp_path / "date=2026-09-13"
    d.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), d / "s.parquet")
    return str(tmp_path / "**" / "*.parquet")


def test_price_at_returns_the_requested_horizon(archive):
    p = price_at(archive, "KXNFLRECYDS-TEST-PLAYER1-50", 60)
    assert p.mins_to_close == 60
    assert p.yes_ask == Decimal("0.41")


def test_price_at_never_returns_a_later_snapshot(archive):
    """Asking for T-120 must give T-180, not T-90. Picking the nearest snapshot in
    absolute terms would leak price information from after the reconstruction time."""
    p = price_at(archive, "KXNFLRECYDS-TEST-PLAYER1-50", 120)
    assert p.mins_to_close == 180
    assert p.mins_to_close >= 120


def test_closing_price_is_the_last_snapshot_before_close(archive):
    c = closing_price(archive, "KXNFLRECYDS-TEST-PLAYER1-50")
    assert c.mins_to_close == 5
    assert c.yes_ask == Decimal("0.48")


def test_missing_market_returns_none(archive):
    assert price_at(archive, "NOT-A-MARKET", 60) is None
    assert closing_price(archive, "NOT-A-MARKET") is None


def test_mid_is_computed_from_both_sides(archive):
    p = price_at(archive, "KXNFLRECYDS-TEST-PLAYER1-50", 60)
    # compare numerically: Decimal scale varies with the arithmetic, and asserting
    # a string representation makes the test brittle without making it stricter
    assert p.mid == Decimal("0.395")


def test_clv_measurable_end_to_end(archive):
    """Entering at T-60 ask and holding to close: the market drifted up 7c, so a
    YES taken at 41c shows positive CLV against a 48c close."""
    from pipeline.backtest.clv import compute_clv_cents
    entry = price_at(archive, "KXNFLRECYDS-TEST-PLAYER1-50", 60).yes_ask
    close = closing_price(archive, "KXNFLRECYDS-TEST-PLAYER1-50").yes_ask
    clv = compute_clv_cents(entry, close, "yes")
    assert clv > 0
    assert clv == Decimal("7")
