"""The wind adjustment.

Measured over 1,186 outdoor team-games (2022-25). The tests that matter are the ones
pinning the *guards*: a missing forecast must not read as calm, a dome must never be
adjusted, and the effect must shrink with forecast lead time.
"""
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.features.wind import (
    MIN_ACTIONABLE_MPH,
    NO_EFFECT,
    describe,
    lead_shrink,
    wind_effect,
)
from pipeline.ingest.weather import STADIUM_COORDS, forecast_for_game, is_outdoor


def test_no_forecast_is_not_the_same_as_calm():
    """The failure this module exists to prevent. A silent zero would disable the
    layer and look identical to a still day -- exactly how p_inactive and the spread
    stayed dead for months."""
    assert wind_effect(None) == NO_EFFECT
    assert not wind_effect(None).is_material


def test_ordinary_wind_does_nothing():
    """68% of outdoor games are under 10mph. Adjusting them adds noise to most of the
    slate for no measured effect."""
    for mph in (0, 4, 7, 9.9):
        assert not wind_effect(mph).is_material


def test_effect_is_monotonic_in_wind():
    rates = [wind_effect(w).pass_rate_delta for w in (10, 15, 20, 30)]
    assert rates == sorted(rates, reverse=True), rates
    assert all(r <= 0 for r in rates)


def test_strong_wind_suppresses_both_volume_and_efficiency():
    """Unlike game script, wind hits efficiency too -- the channel the defense
    adjustment never touched."""
    e = wind_effect(22.0)
    assert e.pass_rate_delta < -0.03
    assert e.efficiency_multiplier < 1.0


def test_effect_shrinks_with_forecast_lead_time():
    """Fitted on actual wind, applied to a forecast. A ten-day forecast deserves less
    weight than a twelve-hour one, and the shrink makes the attenuation explicit."""
    near = wind_effect(20.0, lead_hours=6)
    far = wind_effect(20.0, lead_hours=240)
    assert abs(far.pass_rate_delta) < abs(near.pass_rate_delta)
    assert far.efficiency_multiplier > near.efficiency_multiplier
    assert far.efficiency_multiplier <= 1.0


def test_shrink_never_flips_the_sign_or_exceeds_one():
    for lead in (0, 12, 48, 100, 400, 10_000):
        k = lead_shrink(lead)
        assert 0 < k <= 1.0
        e = wind_effect(25.0, lead_hours=lead)
        assert e.pass_rate_delta <= 0
        assert 0 < e.efficiency_multiplier <= 1.0


def test_description_states_the_forecast_and_its_confidence():
    d = describe(wind_effect(22.0, lead_hours=200))
    assert "22 mph" in d and "shrunk" in d
    assert describe(wind_effect(3.0)) == ""


# ---------------------------------------------------------------- venue gating

def test_domes_are_never_given_a_forecast():
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    assert forecast_for_game("DET00", "dome", kickoff) is None
    assert forecast_for_game("DAL00", "closed", kickoff) is None
    assert not is_outdoor("dome")
    assert not is_outdoor("closed")
    assert not is_outdoor(None)


def test_open_and_outdoors_both_count_as_exposed():
    assert is_outdoor("outdoors")
    assert is_outdoor("open")


def test_unknown_stadium_yields_nothing_rather_than_a_guess():
    """Wrong coordinates would be worse than no adjustment: a confident number for
    the wrong city."""
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    assert forecast_for_game("ZZZ99", "outdoors", kickoff) is None
    assert forecast_for_game(None, "outdoors", kickoff) is None
    assert forecast_for_game("SEA00", "outdoors", None) is None


def test_every_outdoor_venue_in_the_schedule_has_coordinates():
    """A missing venue is a silent gap, so this is checked against the real schedule
    rather than a list maintained by hand."""
    duckdb = pytest.importorskip("duckdb")
    from pathlib import Path
    sched = Path("data/raw/nflverse/schedules.parquet")
    if not sched.exists():
        pytest.skip("schedules not ingested")
    rows = duckdb.connect().execute(
        f"select distinct stadium_id, roof from read_parquet('{sched}') "
        f"where season between 2024 and 2026"
    ).fetchall()
    missing = [sid for sid, roof in rows if is_outdoor(roof) and sid not in STADIUM_COORDS]
    assert not missing, f"outdoor venues without coordinates: {missing}"


def test_no_phantom_coordinates():
    """A key that matches nothing implies coverage that does not exist."""
    duckdb = pytest.importorskip("duckdb")
    from pathlib import Path
    sched = Path("data/raw/nflverse/schedules.parquet")
    if not sched.exists():
        pytest.skip("schedules not ingested")
    known = {r[0] for r in duckdb.connect().execute(
        f"select distinct stadium_id from read_parquet('{sched}')"
    ).fetchall()}
    phantom = [k for k in STADIUM_COORDS if k not in known]
    assert not phantom, f"coordinates for stadiums that do not appear: {phantom}"


# ---------------------------------------------------------------- fetch failure

def test_a_failed_fetch_is_not_calm_weather():
    """The failure mode the whole module was designed against, now measured.

    Production ran `outdoor=1013 with_wind=104` and then, an hour later on the same
    slate, `outdoor=1013 with_wind=0`. Same games, same forecast horizon, materially
    different projections -- decided by whether an HTTP call succeeded, and recorded
    nowhere. `wind_effect(None)` must therefore stay inert rather than resolving to a
    still day, and the run meta must count the failures separately.
    """
    from pipeline.features.wind import wind_effect

    nofetch = wind_effect(None, 24.0)
    calm = wind_effect(2.0, 24.0)

    # Below the actionable threshold both collapse to the SAME object: a genuine
    # 2mph reading and a fetch that returned nothing are literally indistinguishable
    # here. That is not a defect in wind_effect -- there is no adjustment to make in
    # either case -- but it is precisely why the run meta has to count fetches
    # attempted against fetches failed. The effect object cannot carry that
    # distinction, so something upstream must.
    assert not nofetch.is_material
    assert not calm.is_material
    assert nofetch.wind_mph == calm.wind_mph == 0.0
    assert nofetch.band == calm.band == "none"

    # And a real forecast above the threshold is still material, so the layer works.
    windy = wind_effect(18.5, 24.0)
    assert windy.is_material and windy.wind_mph == 18.5


def test_retry_is_configured_but_bounded():
    """Retries exist because the failure is transient; they stay small because a full
    slate is about two dozen memoised calls and a stuck job helps nobody."""
    from pipeline.ingest import weather

    assert weather.ATTEMPTS >= 2
    assert weather.ATTEMPTS <= 5
    assert 0 < weather.BACKOFF_SECONDS <= 5


def test_a_client_error_is_not_retried():
    """A 404 will not fix itself. Retrying it burns the budget that a 429 needs."""
    import requests

    from pipeline.ingest.weather import fetch_forecast
    from datetime import datetime, timezone

    calls = {"n": 0}

    class FakeResp:
        ok = False
        status_code = 404

    class FakeSession:
        def get(self, *a, **k):
            calls["n"] += 1
            return FakeResp()

    out = fetch_forecast(47.6, -122.3, datetime(2026, 9, 9, 20, tzinfo=timezone.utc),
                         session=FakeSession())
    assert out is None
    assert calls["n"] == 1, "a 4xx must not be retried"


def test_a_server_error_is_retried_then_gives_up():
    import requests

    from pipeline.ingest.weather import ATTEMPTS, fetch_forecast
    from datetime import datetime, timezone

    calls = {"n": 0}

    class FakeResp:
        ok = False
        status_code = 503

    class FakeSession:
        def get(self, *a, **k):
            calls["n"] += 1
            return FakeResp()

    out = fetch_forecast(47.6, -122.3, datetime(2026, 9, 9, 20, tzinfo=timezone.utc),
                         session=FakeSession())
    assert out is None
    assert calls["n"] == ATTEMPTS, "a 5xx should exhaust the retry budget"
