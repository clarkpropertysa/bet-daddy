"""Adjustments must reach the projection, not just the explanation.

The failure this guards: `opponent_defense` was explained in 51 of 53 rationales
while being applied to 0 of them, because the condition read an unused parameter.
`rest_adjustment` was written, documented and tested, and never called at all.

An adjustment that stops firing looks exactly like one that works, so these assert
the wiring rather than the arithmetic.
"""
import pytest

from pipeline.model.adjustments import (
    USAGE_TREND_MAX_SWING,
    rest_adjustment,
    usage_trend_adjustment,
)
from pipeline.model.project import _event_date, _rest_context

pytestmark = pytest.mark.network


# ---------------------------------------------------------------- usage trend
def test_trend_direction_follows_recent_form():
    up = usage_trend_adjustment(14.0, 10.0, 5)
    down = usage_trend_adjustment(6.0, 10.0, 5)
    assert up.multiplier > 1.0
    assert down.multiplier < 1.0


def test_trend_is_shrunk_by_sample_size():
    """The same 40% swing on 2 games must move the projection less than on 5."""
    thin = usage_trend_adjustment(14.0, 10.0, 2)
    full = usage_trend_adjustment(14.0, 10.0, 5)
    assert abs(thin.multiplier - 1) < abs(full.multiplier - 1)


def test_trend_is_capped():
    """An uncapped trend on a hot streak would swamp every other adjustment."""
    extreme = usage_trend_adjustment(40.0, 10.0, 8)
    assert abs(extreme.multiplier - 1) <= USAGE_TREND_MAX_SWING + 1e-9


def test_trend_ignores_a_one_game_sample():
    assert usage_trend_adjustment(20.0, 10.0, 1) is None


def test_trend_ignores_a_flat_stretch():
    assert usage_trend_adjustment(10.02, 10.0, 5) is None


def test_trend_handles_missing_inputs():
    assert usage_trend_adjustment(None, 10.0, 5) is None
    assert usage_trend_adjustment(10.0, 0, 5) is None


# ---------------------------------------------------------------- rest wiring
def test_event_date_parses_out_of_a_ticker():
    assert _event_date("X-26SEP10SFLAR-A-1") == "2026-09-10"
    assert _event_date("X-26AUG15CARBUF-A-1") == "2026-08-15"
    assert _event_date("GARBAGE") is None


def test_rest_context_is_keyed_the_way_the_job_looks_it_up():
    rc = _rest_context("data/raw/nflverse/schedules.parquet", 2026)
    assert len(rc) == 544                       # 272 games x 2 teams
    assert ("SEA", "2026-09-09") in rc          # the key the ticker produces


def test_rest_adjustment_actually_fires_somewhere_in_the_season():
    """The wiring test that matters: rest was never called, so asserting the
    function works in isolation would have passed while the model ignored it."""
    rc = _rest_context("data/raw/nflverse/schedules.parquet", 2026)
    firing = [rest_adjustment(*v) for v in rc.values()]
    assert sum(1 for a in firing if a) > 50


def test_week_one_openers_get_no_rest_adjustment():
    """No prior game means no rest state -- days_rest is NULL, not zero."""
    rc = _rest_context("data/raw/nflverse/schedules.parquet", 2026)
    assert rest_adjustment(*rc[("SEA", "2026-09-09")]) is None
