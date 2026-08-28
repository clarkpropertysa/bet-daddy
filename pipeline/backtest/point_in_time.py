"""Point-in-time correctness (Section 8).

The rule: a projection made for a game may only use data that existed BEFORE that
projection's cutoff. Any leakage of post-cutoff information invalidates every metric
downstream, and the failure is silent -- a leaky backtest looks like a brilliant model.

This module makes the cutoff explicit and testable rather than a convention people
remember to follow. Feature builders take an `as_of` and are filtered by it; the
guard then asserts the filtered frame really does predate the cutoff.
"""
from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pyarrow as pa


class LeakageError(AssertionError):
    """Raised when a feature set contains data at or after its own cutoff."""


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def filter_as_of(table: pa.Table, as_of: datetime, ts_column: str) -> pa.Table:
    """Keep only rows strictly before `as_of`.

    Strictly before, not <=: a row stamped exactly at the cutoff is ambiguous, and
    on a T-60 reconstruction the ambiguous row is usually the one that leaks.
    """
    con = duckdb.connect()
    con.register("t", table)
    return con.execute(
        f"select * from t where {ts_column} < ?", [_utc(as_of)]
    ).to_arrow_table()


def assert_no_leakage(table: pa.Table, as_of: datetime, ts_column: str) -> None:
    """Fail loudly if any row is at or after the cutoff."""
    if table.num_rows == 0:
        return
    con = duckdb.connect()
    con.register("t", table)
    # cast to varchar: duckdb needs pytz to materialise a tz-aware datetime, and an
    # extra dependency for an error message is not worth it
    n, worst = con.execute(
        f"select count(*), cast(max({ts_column}) as varchar) from t "
        f"where {ts_column} >= ?",
        [_utc(as_of)],
    ).fetchone()
    if n:
        raise LeakageError(
            f"{n} row(s) at or after cutoff {_utc(as_of).isoformat()} "
            f"in column {ts_column!r} (latest {worst}). A projection built from this "
            f"would be using information it could not have had."
        )


def assert_features_predate_kickoff(
    feature_as_of: datetime, kickoff_utc: datetime
) -> None:
    """A projection's feature cutoff must precede kickoff.

    Guards the most damaging leak available here: building a 'prediction' from the
    completed game's own play-by-play.
    """
    if _utc(feature_as_of) >= _utc(kickoff_utc):
        raise LeakageError(
            f"feature_as_of {_utc(feature_as_of).isoformat()} is not before kickoff "
            f"{_utc(kickoff_utc).isoformat()} -- the projection would include the "
            f"game it is predicting."
        )
