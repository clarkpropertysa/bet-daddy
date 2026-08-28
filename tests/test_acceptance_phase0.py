"""Phase 0 acceptance (Section 11).

  "Phase 0 is done when a single command loads real NFL data and a test asserts
   specific known-correct values against the loaded rows."

Every value below was read from live nflverse data on 2026-08-28 and hand-checked.
Nothing here is mocked, seeded, or fixtured -- per Section 0 rule 3, a fake number
that survives into the UI destroys the point of the tool.
"""
import polars as pl
import pytest

from pipeline.common import config
from pipeline.ingest.nflverse import DATASETS, SchemaDriftError, fetch

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def stats_2025() -> pl.DataFrame:
    return fetch("player_stats_week", 2025)


@pytest.fixture(scope="module")
def schedules() -> pl.DataFrame:
    return fetch("schedules")


# ---------------------------------------------------------------- known outcomes
def test_flacco_470_yards_vs_chi_week9_2025(stats_2025):
    """Joe Flacco's highest passing-yard game of 2025: 470 vs CHI in week 9."""
    row = stats_2025.filter(
        (pl.col("player_display_name") == "Joe Flacco")
        & (pl.col("season_type") == "REG")
        & (pl.col("week") == 9)
    )
    assert row.height == 1
    r = row.row(0, named=True)
    assert r["passing_yards"] == 470
    assert r["passing_tds"] == 4
    assert r["opponent_team"] == "CHI"
    assert r["team"] == "CIN"


def test_nacua_165_receiving_yards_week21_2025(stats_2025):
    """Puka Nacua, 2025 postseason week 21: 9 receptions, 165 yards, 1 TD."""
    row = stats_2025.filter(
        (pl.col("player_display_name") == "Puka Nacua")
        & (pl.col("season_type") == "POST")
        & (pl.col("week") == 21)
    )
    assert row.height == 1
    r = row.row(0, named=True)
    assert r["receiving_yards"] == 165
    assert r["receptions"] == 9
    assert r["targets"] == 14


def test_2025_season_is_complete_through_super_bowl(stats_2025):
    assert stats_2025.height == 19_422
    assert stats_2025["week"].max() == 22
    assert set(stats_2025["season_type"].unique()) == {"REG", "POST"}


# ---------------------------------------------------------------- schedule
def test_2026_season_opens_wednesday_sept_9_ne_at_sea(schedules):
    """2026 opener: NE @ SEA, Wed 2026-09-09, Lumen Field."""
    wk1 = schedules.filter((pl.col("season") == 2026) & (pl.col("week") == 1))
    opener = wk1.sort("gameday", "gametime").row(0, named=True)
    assert opener["game_id"] == "2026_01_NE_SEA"
    assert opener["gameday"] == "2026-09-09"
    assert opener["weekday"] == "Wednesday"
    assert opener["stadium"] == "Lumen Field"


def test_2026_schedule_is_full_272_games(schedules):
    assert schedules.filter(pl.col("season") == 2026).height == 272


def test_week1_2026_includes_melbourne_international_game(schedules):
    """SF vs LA at the MCG -- a ~10,000 mile trip in week 1 that the rest/travel
    module (Section 5.3) must not treat as an ordinary road game."""
    g = schedules.filter(pl.col("game_id") == "2026_01_SF_LA").row(0, named=True)
    assert g["stadium"] == "Melbourne Cricket Ground"


# ---------------------------------------------------------------- integrity
def test_snap_counts_2025_loads_with_required_columns():
    df = fetch("snap_counts", 2025)
    assert df.height == 26_612
    for c in DATASETS["snap_counts"].required:
        assert c in df.columns


def test_schema_drift_is_detected_not_ignored(monkeypatch):
    """A dropped upstream column must fail loudly. depth_charts_2026 really did drop
    jersey_number/full_name/depth_team, so this is a live failure mode."""
    ds = DATASETS["schedules"]
    monkeypatch.setitem(
        DATASETS, "schedules",
        type(ds)(ds.name, ds.release, ds.filename, ds.seasonal,
                 ds.required + ("column_that_does_not_exist",)),
    )
    with pytest.raises(SchemaDriftError, match="schema drift"):
        fetch("schedules", force=False)


def test_no_fabricated_rows_in_raw_layer():
    """Section 0 rule 3: no mocked or placeholder sports data, ever."""
    raw = config.RAW_DIR / "nflverse"
    files = list(raw.glob("*.parquet"))
    assert files, "no raw nflverse data present -- run pipeline.ingest.nflverse"
    for f in files:
        df = pl.read_parquet(f, n_rows=200)
        for col in df.columns:
            if df[col].dtype == pl.Utf8:
                vals = {str(v).lower() for v in df[col].drop_nulls().unique().to_list()[:200]}
                assert not (vals & {"test", "placeholder", "mock", "dummy", "sample", "fake"}), \
                    f"suspicious placeholder value in {f.name}:{col}"
