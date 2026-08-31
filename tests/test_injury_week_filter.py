"""The injury report is a weekly snapshot, not a season-long accumulation.

`injured_out` used to select `distinct gsis_id` across the entire season file, so any
player ever designated Out stayed out for every later projection. Measured on 2025:
726 distinct players cumulatively against 48 in week 1 and 108 in week 18. Because the
projection skips non-starters *silently*, roughly 186 skill players would have been
benched and their backups promoted onto the board with nothing raised.

These tests use the real 2025 injury file rather than a fixture: the failure was a
property of how injury reports accumulate over a season, and a three-row fixture cannot
express it.
"""
from pathlib import Path

import pytest

from pipeline.features.starters import injured_out

INJURIES = Path("data/raw/nflverse/injuries_2025.parquet")
pytestmark = pytest.mark.skipif(
    not INJURIES.exists(), reason="nflverse injuries not ingested"
)


def test_a_week_returns_far_fewer_than_the_whole_season():
    """The bug, stated as a test."""
    cumulative = injured_out(str(INJURIES))
    week_one = injured_out(str(INJURIES), week=1)
    assert len(week_one) < len(cumulative) / 4
    assert 20 < len(week_one) < 200, len(week_one)


def test_no_week_is_out_for_the_whole_season():
    """Late-season weeks must not inherit every earlier week's absences."""
    counts = {wk: len(injured_out(str(INJURIES), week=wk)) for wk in (1, 8, 18)}
    cumulative = len(injured_out(str(INJURIES)))
    for wk, n in counts.items():
        assert n < cumulative / 3, f"week {wk} returned {n} of {cumulative}"


def test_weeks_differ_from_each_other():
    """If the filter silently did nothing, every week would return the same set."""
    w1 = injured_out(str(INJURIES), week=1)
    w10 = injured_out(str(INJURIES), week=10)
    assert w1 != w10
    # Some overlap is expected (long-term injuries), but they must not be identical.
    assert len(w1 & w10) < min(len(w1), len(w10))


def test_season_filter_excludes_other_seasons():
    """A file holding one season should be unchanged; a wrong season yields nothing."""
    assert injured_out(str(INJURIES), week=1, season=2025)
    assert injured_out(str(INJURIES), week=1, season=1999) == set()


def test_missing_file_is_empty_not_an_error():
    """No injury report is the normal preseason state and must not fail a run."""
    assert injured_out(None) == set()
    assert injured_out("data/raw/nflverse/does_not_exist.parquet", week=1) == set()
