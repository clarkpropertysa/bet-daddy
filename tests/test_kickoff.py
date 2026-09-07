"""The board ages picks off at KICKOFF, and kickoff comes from the schedule in Eastern.

Two bugs met here. Kalshi's `close_time` is a settlement deadline roughly two days after
the game, and the board filtered on it -- so every Week 1 pick would have stayed listed
through its own game and for two days afterwards. And nflverse's `gametime` is Eastern
while the parser stamped it UTC, putting every kickoff four hours early.

The tell for the second was the gap between the two: a settlement window of "2 days and
4 hours" is not a window anyone designed. It is exactly two days once the zone is right.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.model.project import _venue_index

SCHEDULE = Path("data/raw/nflverse/schedules.parquet")
needs = pytest.mark.skipif(not SCHEDULE.exists(), reason="schedules not ingested")


@needs
def test_an_evening_eastern_kickoff_crosses_into_the_next_utc_day():
    """New England at Seattle kicks off 20:20 ET on 9 September, which is 00:20 UTC on
    the 10th. Read as UTC it was 2026-09-09T20:20Z -- four hours early and on the wrong
    calendar day."""
    v = _venue_index(str(SCHEDULE), 2026)
    ko = v.get("2026-09-09|SEA")
    if ko is None:
        pytest.skip("2026 week 1 not in this schedule file")
    assert ko[2] == datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)


@needs
def test_a_one_oclock_eastern_kickoff_is_seventeen_hundred_utc():
    v = _venue_index(str(SCHEDULE), 2026)
    ko = v.get("2026-09-13|PIT")
    if ko is None:
        pytest.skip("2026 week 1 not in this schedule file")
    assert ko[2] == datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)


@needs
def test_every_kickoff_is_timezone_aware_and_in_utc():
    """A naive datetime compared against `now()` in Postgres is a silent four-hour
    error, which is precisely the failure this file exists for."""
    v = _venue_index(str(SCHEDULE), 2026)
    assert v
    for key, (_sid, _roof, ko) in v.items():
        if ko is None:
            continue
        assert ko.tzinfo is not None, key
        assert ko.utcoffset().total_seconds() == 0, key


@needs
def test_kickoffs_land_in_the_hours_football_is_played():
    """Eastern kickoffs run roughly 09:30 (London) to 20:20. In UTC that is 13:30 to
    just past midnight. If the zone were wrong the distribution would shift wholesale."""
    v = _venue_index(str(SCHEDULE), 2026)
    hours = sorted({ko.hour for _, (_s, _r, ko) in v.items() if ko})
    assert hours, "no kickoffs parsed"
    # every kickoff is either afternoon/evening UTC or just after midnight UTC
    assert all(h >= 13 or h <= 4 for h in hours), hours
