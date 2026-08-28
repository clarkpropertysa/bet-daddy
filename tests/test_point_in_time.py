"""Point-in-time correctness. A leaky backtest looks like a brilliant model."""
from datetime import datetime, timedelta, timezone

import pyarrow as pa
import pytest

from pipeline.backtest.point_in_time import (
    LeakageError,
    assert_features_predate_kickoff,
    assert_no_leakage,
    filter_as_of,
)

T0 = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)


def _tbl(offsets_mins):
    return pa.Table.from_pylist(
        [{"ts": T0 + timedelta(minutes=m), "v": i} for i, m in enumerate(offsets_mins)],
        schema=pa.schema([("ts", pa.timestamp("us", tz="UTC")), ("v", pa.int64())]),
    )


def test_filter_keeps_only_rows_before_cutoff():
    out = filter_as_of(_tbl([-120, -60, -1, 0, 30]), T0, "ts")
    assert out.num_rows == 3


def test_row_exactly_at_cutoff_is_excluded():
    """Strictly before, not <=. On a T-60 reconstruction the ambiguous row is
    usually the one that leaks."""
    assert filter_as_of(_tbl([0]), T0, "ts").num_rows == 0


def test_assert_no_leakage_passes_on_clean_data():
    assert_no_leakage(_tbl([-120, -60]), T0, "ts")


def test_assert_no_leakage_raises_on_future_row():
    with pytest.raises(LeakageError, match="at or after cutoff"):
        assert_no_leakage(_tbl([-60, 15]), T0, "ts")


def test_leakage_error_names_the_offending_count():
    with pytest.raises(LeakageError, match="2 row"):
        assert_no_leakage(_tbl([-60, 5, 30]), T0, "ts")


def test_empty_table_is_not_leakage():
    assert_no_leakage(_tbl([]), T0, "ts")


def test_features_must_predate_kickoff():
    assert_features_predate_kickoff(T0 - timedelta(hours=1), T0)


def test_features_at_or_after_kickoff_are_rejected():
    """The most damaging leak available: building a 'prediction' from the completed
    game's own play-by-play."""
    with pytest.raises(LeakageError, match="not before kickoff"):
        assert_features_predate_kickoff(T0, T0)
    with pytest.raises(LeakageError, match="not before kickoff"):
        assert_features_predate_kickoff(T0 + timedelta(hours=3), T0)


def test_naive_datetimes_are_treated_as_utc():
    assert_features_predate_kickoff(
        datetime(2026, 9, 13, 16, 0), datetime(2026, 9, 13, 17, 0))
