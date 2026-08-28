"""With/without splits -- the module most able to lie convincingly (Section 5.2)."""
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.features.splits import (
    SKILL_POSITIONS,
    build_availability,
    build_with_without,
)
from pipeline.features.usage import build_player_game_usage

pytestmark = pytest.mark.network

PBP = "data/raw/nflverse/pbp_2025.parquet"
SNAPS = "data/raw/nflverse/snap_counts_2025.parquet"
PLAYERS = "data/raw/nflverse/players.parquet"


@pytest.fixture(scope="module")
def parts():
    usage = build_player_game_usage(PBP)
    avail = build_availability(SNAPS, PLAYERS)
    players = pq.read_table(PLAYERS)
    return usage, avail, players


@pytest.fixture(scope="module")
def con(parts):
    usage, avail, players = parts
    c = duckdb.connect()
    c.register("splits", build_with_without(usage, avail, players, "target_share"))
    c.register("avail", avail)
    c.register("players", players)
    return c


def test_availability_uses_snaps_not_targets(parts):
    """A receiver who played 40 snaps and drew zero targets is PRESENT.

    Inferring availability from targets would mark him absent and manufacture the
    very usage-vacancy effect the module exists to measure."""
    usage, avail, _ = parts
    c = duckdb.connect()
    c.register("usage", usage)
    c.register("avail", avail)
    n = c.execute("""
        select count(*) from avail a
        left join usage u on u.player_id = a.player_id and u.game_id = a.game_id
        where u.player_id is null
    """).fetchone()[0]
    assert n > 0, "expected players with snaps but no targets/carries"


def test_only_skill_position_teammates_are_considered(con):
    """An offensive tackle's absence cannot free targets. Before this gate, OTs
    drove two of the five largest 2025 splits -- pure injury co-occurrence."""
    bad = con.execute(f"""
        select count(*) from splits s
        join players p on p.gsis_id = s.teammate_id
        where p.position not in ({", ".join(f"'{x}'" for x in SKILL_POSITIONS)})
    """).fetchone()[0]
    assert bad == 0


def test_most_splits_are_suppressed(con):
    """Most with/without splits are noise. If the suppression rate is low, the
    sample-size gate has silently stopped working."""
    total, supp = con.execute(
        "select count(*), sum(case when suppressed then 1 else 0 end) from splits"
    ).fetchone()
    assert supp / total > 0.7


def test_significance_requires_ci_excluding_zero(con):
    bad = con.execute("""
        select count(*) from splits
        where significant and ci_low is not null and ci_low <= 0 and ci_high >= 0
    """).fetchone()[0]
    assert bad == 0


def test_ci_brackets_the_delta(con):
    bad = con.execute("""
        select count(*) from splits
        where delta is not null and not (ci_low <= delta and delta <= ci_high)
    """).fetchone()[0]
    assert bad == 0


def test_delta_equals_without_minus_with(con):
    bad = con.execute("""
        select count(*) from splits
        where delta is not null
          and abs(delta - (mean_without - mean_with)) > 1e-9
    """).fetchone()[0]
    assert bad == 0


def test_confound_diagnostic_is_populated(con):
    """Every split with a 'without' sample must report how many OTHER regulars were
    also out, otherwise the UI cannot tell a clean split from a decimated roster."""
    missing = con.execute("""
        select count(*) from splits
        where n_without > 0 and confound_regulars_out is null
    """).fetchone()[0]
    assert missing == 0


def test_headline_signals_carry_visible_confounding(con):
    """The largest 2025 split (Michael Wilson without Marvin Harrison Jr.) happens
    in games where several other regulars were also out. The number must be exposed,
    not hidden, so a large delta is not mistaken for a clean read."""
    row = con.execute("""
        select confound_regulars_out from splits
        where not suppressed and significant and delta is not null
        order by delta desc limit 1
    """).fetchone()
    assert row[0] > 2.0


def test_nothing_is_dropped_only_flagged(con):
    """Failing rows must be returned with suppressed=true, never filtered away."""
    n = con.execute("select count(*) from splits where suppressed").fetchone()[0]
    assert n > 0
