"""The leakage guard must actually guard.

point_in_time.py was written, documented and tested -- and imported by nothing outside
its own test file. `assert_no_leakage` and `assert_features_predate_kickoff` were never
called in production, so the protection they describe did not exist.

The module's own docstring names the stakes: "a leaky backtest looks like a brilliant
model". These tests pin that the guard is reachable from the projection and refuses the
two cases that matter.
"""
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.backtest.point_in_time import (
    LeakageError,
    assert_features_predate_kickoff,
)
from pipeline.model.project import _assert_pbp_predates_slate

KICK = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)


def test_a_price_taken_after_kickoff_is_refused():
    """In settled mode this is the whole integrity question: a snapshot from after
    kickoff prices a game whose result is already known."""
    with pytest.raises(LeakageError):
        assert_features_predate_kickoff(KICK + timedelta(minutes=1), KICK)
    with pytest.raises(LeakageError):
        assert_features_predate_kickoff(KICK, KICK)   # exactly at kickoff is ambiguous


def test_a_price_before_kickoff_passes():
    assert_features_predate_kickoff(KICK - timedelta(hours=2), KICK) is None


def test_naive_timestamps_are_treated_as_utc_not_rejected():
    """A naive datetime is common in this codebase; it must not silently pass a check
    it should fail."""
    with pytest.raises(LeakageError):
        assert_features_predate_kickoff(
            (KICK + timedelta(hours=1)).replace(tzinfo=None), KICK
        )


def test_the_projection_refuses_pbp_that_contains_the_slate(tmp_path):
    """The most damaging leak available: blending current-season play-by-play that
    already holds the game being projected."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "pbp.parquet"
    pq.write_table(pa.table({"game_date": ["2026-09-13"]}), path)
    venue = {"2026-09-13|SEA": ("SEA00", "outdoors", KICK)}
    with pytest.raises(LeakageError):
        _assert_pbp_predates_slate(str(path), [], venue)


def test_pbp_that_stops_before_the_slate_is_fine(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "pbp.parquet"
    pq.write_table(pa.table({"game_date": ["2026-09-06"]}), path)
    venue = {"2026-09-13|SEA": ("SEA00", "outdoors", KICK)}
    _assert_pbp_predates_slate(str(path), [], venue)


def test_a_missing_or_odd_file_does_not_fail_the_run(tmp_path):
    """The guard must catch leakage, not become a new way for the pipeline to die."""
    venue = {"2026-09-13|SEA": ("SEA00", "outdoors", KICK)}
    _assert_pbp_predates_slate(str(tmp_path / "nope.parquet"), [], venue)
    _assert_pbp_predates_slate("nope.parquet", [], {})


def test_the_guard_is_actually_called_by_the_projection():
    """The failure this whole file exists for: a guard nothing invokes."""
    import inspect
    from pipeline.model import project

    src = inspect.getsource(project)
    assert "assert_features_predate_kickoff(" in src
    assert "_assert_pbp_predates_slate(" in src
    assert "leakage_price_after_kickoff" in src
