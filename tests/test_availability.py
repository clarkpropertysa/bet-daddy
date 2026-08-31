"""P(no offensive snap) from the injury report.

`VolumeProjection.p_inactive` was implemented in the simulator and never set by the
projection, so every prop was priced as though the player were certain to play. The
tests that matter here are the ones pinning the *shape* of the table: a monotonic
relationship with severity, and a clear separation between "not on the injury report"
and "on it with no designation".
"""
from pathlib import Path

import pytest

from pipeline.features.availability import (
    DEFAULT_HEALTHY,
    MIN_CELL_N,
    PRIOR,
    InactivityTable,
    build_inactivity_table,
    status_lookup,
)

DATA = Path("data/raw/nflverse")
HAVE_DATA = (DATA / "injuries_2025.parquet").exists() and (
    DATA / "snap_counts_2025.parquet"
).exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="nflverse data not ingested")


# ---------------------------------------------------------------- unit behaviour

def _table(cells: dict | None = None) -> InactivityTable:
    """Cell keys are (report_status, practice_status) tuples, so not **kwargs."""
    rates = dict(cells or {})
    return InactivityTable(rates, {k: 999 for k in rates}, 2025)


def test_a_player_not_on_the_report_is_not_treated_as_listed():
    """"(none)" means listed without a designation -- 11.9% -- which is very different
    from not being listed at all. Conflating them puts injury risk on every healthy
    starter in the league."""
    t = _table({("(none)", "Full Participation in Practice"): 0.12})
    assert t.for_player(None) == DEFAULT_HEALTHY
    assert t.for_player(("(none)", "Full Participation in Practice")) == 0.12
    assert t.for_player(None) < 0.05


def test_thin_cells_fall_back_to_the_prior_rather_than_their_own_noise():
    thin = InactivityTable(
        {("Questionable", "Limited Participation in Practice"): 1.0},
        {("Questionable", "Limited Participation in Practice"): MIN_CELL_N - 1},
        2025,
    )
    assert thin.probability("Questionable", "Limited Participation in Practice") == (
        PRIOR["Questionable"]
    )


def test_unknown_status_falls_back_rather_than_raising():
    t = _table()
    assert t.probability("Probable", "Some New Category") == DEFAULT_HEALTHY
    assert t.probability("Out", "anything") == PRIOR["Out"]


def test_empty_table_is_detectable():
    """The projection must be able to tell a missing table from a calm week."""
    assert InactivityTable({}, {}, 2025).is_empty
    assert not _table({("Out", "x"): 1.0}).is_empty


# ---------------------------------------------------------------- measured shape

@needs_data
def test_measured_rates_are_monotonic_in_severity():
    """Out > Questionable > listed-but-undesignated. If this inverts, the join broke."""
    t = build_inactivity_table(
        str(DATA / "injuries_2025.parquet"),
        str(DATA / "snap_counts_2025.parquet"),
        str(DATA / "players.parquet"),
        2025,
    )
    assert not t.is_empty
    out = t.probability("Out", "Did Not Participate In Practice")
    ques = t.probability("Questionable", "Limited Participation in Practice")
    none = t.probability("(none)", "Full Participation in Practice")
    assert out > ques > none, (out, ques, none)


@needs_data
def test_out_players_essentially_never_play():
    t = build_inactivity_table(
        str(DATA / "injuries_2025.parquet"),
        str(DATA / "snap_counts_2025.parquet"),
        str(DATA / "players.parquet"),
        2025,
    )
    assert t.probability("Out", "Did Not Participate In Practice") > 0.98


@needs_data
def test_questionable_is_a_real_risk_not_a_rounding_error():
    """The whole point. Questionable players were treated as certain to play; they
    miss roughly four games in ten."""
    t = build_inactivity_table(
        str(DATA / "injuries_2025.parquet"),
        str(DATA / "snap_counts_2025.parquet"),
        str(DATA / "players.parquet"),
        2025,
    )
    p = t.probability("Questionable", "Limited Participation in Practice")
    assert 0.25 < p < 0.60, p


@needs_data
def test_status_lookup_is_scoped_to_one_week():
    w1 = status_lookup(str(DATA / "injuries_2025.parquet"), 2025, 1)
    w10 = status_lookup(str(DATA / "injuries_2025.parquet"), 2025, 10)
    assert w1 and w10
    assert w1 != w10


def test_missing_files_degrade_to_an_empty_table_not_an_exception():
    """No injury report is the normal preseason state."""
    t = build_inactivity_table("nope.parquet", "nope.parquet", "nope.parquet", 2026)
    assert t.is_empty
    assert status_lookup("nope.parquet", 2026, 1) == {}
