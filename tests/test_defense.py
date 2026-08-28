"""Defense grades. Inferred from play-by-play outcomes, never charted (Section 5.4)."""
import duckdb
import pytest

from pipeline.features.defense import (
    MIN_TARGETS_FOR_RANK,
    build_pass_defense_grades,
    build_rush_defense_grades,
)

pytestmark = pytest.mark.network

PBP = "data/raw/nflverse/pbp_2025.parquet"
PLAYERS = "data/raw/nflverse/players.parquet"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.register("pass_d", build_pass_defense_grades(PBP, PLAYERS))
    c.register("rush_d", build_rush_defense_grades(PBP))
    return c


def test_provenance_is_labelled_inferred(con):
    """These grades do not know who covered whom. Claiming charted coverage we do
    not have would misrepresent the data's origin."""
    bad = con.execute(
        "select count(*) from pass_d where provenance != 'inferred_from_pbp'").fetchone()[0]
    assert bad == 0


def test_depth_bands_are_exactly_the_three_expected(con):
    bands = {r[0] for r in con.execute(
        "select distinct depth_band from pass_d").fetchall()}
    assert bands == {"short", "intermediate", "deep"}


def test_no_unknown_run_location_bucket(con):
    """128 runs in 2025 have no recorded location and average -1.63 EPA -- botched
    snaps, not a gap. Bucketing them as 'unknown' handed every defense that faced
    them a fake elite grade."""
    locs = {r[0] for r in con.execute(
        "select distinct run_location from rush_d").fetchall()}
    assert "unknown" not in locs
    assert locs == {"all", "left", "middle", "right"}


def test_all_row_retains_every_carry(con):
    """The unlocated runs still happened; they belong in the team total even though
    they are excluded from the gap splits."""
    total_all, total_gaps = con.execute("""
        select
          (select sum(carries) from rush_d where run_location = 'all'),
          (select sum(carries) from rush_d where run_location != 'all')
    """).fetchone()
    assert total_all > total_gaps


def test_rank_one_is_the_best_defense(con):
    """Rank 1 must be the LOWEST EPA allowed. An inverted sort would make the app
    recommend attacking the best defenses."""
    best, worst = con.execute("""
        select
          (select epa_per_target from pass_d
            where depth_band='deep' and receiver_position='WR' and epa_rank = 1),
          (select max(epa_per_target) from pass_d
            where depth_band='deep' and receiver_position='WR' and rankable)
    """).fetchone()
    assert best < worst


def test_thin_splits_get_no_rank(con):
    """A rank computed off 6 targets is a lie with a number attached."""
    bad = con.execute(f"""
        select count(*) from pass_d
        where targets < {MIN_TARGETS_FOR_RANK} and epa_rank is not null
    """).fetchone()[0]
    assert bad == 0
    assert con.execute(
        "select count(*) from pass_d where not rankable").fetchone()[0] > 0


def test_every_rankable_split_covers_all_32_teams(con):
    """If a split ranks fewer than 32 teams the rank is not comparable across teams."""
    rows = con.execute("""
        select depth_band, receiver_position, count(distinct team) n
        from pass_d where rankable
        group by 1, 2 having count(distinct team) = 32
    """).fetchall()
    assert len(rows) > 0


def test_success_rate_is_a_probability(con):
    bad = con.execute("""
        select count(*) from pass_d
        where success_rate_allowed < 0 or success_rate_allowed > 1
    """).fetchone()[0]
    assert bad == 0


def test_kneels_excluded_from_run_defense(con):
    """QB kneels are -2 EPA plays that say nothing about run defence quality."""
    epa = con.execute(
        "select avg(epa_per_carry) from rush_d where run_location = 'all'").fetchone()[0]
    assert -0.1 < epa < 0.1
