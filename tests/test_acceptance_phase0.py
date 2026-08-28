"""Phase 0 acceptance (Section 11).

  "Phase 0 is done when a single command loads real NFL data and a test asserts
   specific known-correct values against the loaded rows."

Every value below was read from live nflverse data on 2026-08-28 and hand-checked.
Nothing here is mocked, seeded, or fixtured -- per Section 0 rule 3, a fake number
that survives into the UI destroys the point of the tool.
"""
import duckdb
import pyarrow as pa
import pytest

from pipeline.common import config
from pipeline.ingest.nflverse import DATASETS, SchemaDriftError, fetch

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def con():
    return duckdb.connect()


@pytest.fixture(scope="module")
def stats_2025(con) -> pa.Table:
    t = fetch("player_stats_week", 2025)
    con.register("stats", t)
    return t


@pytest.fixture(scope="module")
def schedules(con) -> pa.Table:
    t = fetch("schedules")
    con.register("sched", t)
    return t


# ---------------------------------------------------------------- known outcomes
def test_flacco_470_yards_vs_chi_week9_2025(con, stats_2025):
    """Joe Flacco's highest passing-yard game of 2025: 470 vs CHI in week 9."""
    r = con.execute("""
        select passing_yards, passing_tds, opponent_team, team
        from stats
        where player_display_name = 'Joe Flacco'
          and season_type = 'REG' and week = 9
    """).fetchall()
    assert len(r) == 1
    yards, tds, opp, team = r[0]
    assert yards == 470
    assert tds == 4
    assert opp == "CHI"
    assert team == "CIN"


def test_nacua_165_receiving_yards_week21_2025(con, stats_2025):
    """Puka Nacua, 2025 postseason week 21: 9 receptions, 165 yards, 14 targets."""
    r = con.execute("""
        select receiving_yards, receptions, targets
        from stats
        where player_display_name = 'Puka Nacua'
          and season_type = 'POST' and week = 21
    """).fetchall()
    assert len(r) == 1
    assert r[0] == (165, 9, 14)


def test_2025_season_is_complete_through_super_bowl(con, stats_2025):
    n, maxw = con.execute("select count(*), max(week) from stats").fetchone()
    assert n == 19_422
    assert maxw == 22
    types = {r[0] for r in con.execute("select distinct season_type from stats").fetchall()}
    assert types == {"REG", "POST"}


# ---------------------------------------------------------------- schedule
def test_2026_season_opens_wednesday_sept_9_ne_at_sea(con, schedules):
    """2026 opener: NE @ SEA, Wed 2026-09-09, Lumen Field."""
    r = con.execute("""
        select game_id, gameday, weekday, stadium
        from sched where season = 2026 and week = 1
        order by gameday, gametime limit 1
    """).fetchone()
    assert r == ("2026_01_NE_SEA", "2026-09-09", "Wednesday", "Lumen Field")


def test_2026_schedule_is_full_272_games(con, schedules):
    n = con.execute("select count(*) from sched where season = 2026").fetchone()[0]
    assert n == 272


def test_week1_2026_includes_melbourne_international_game(con, schedules):
    """SF vs LA at the MCG -- a ~10,000 mile trip in week 1 that the rest/travel
    module (Section 5.3) must not treat as an ordinary road game."""
    r = con.execute(
        "select stadium from sched where game_id = '2026_01_SF_LA'").fetchone()
    assert r[0] == "Melbourne Cricket Ground"


# ---------------------------------------------------------------- integrity
def test_snap_counts_2025_loads_with_required_columns():
    t = fetch("snap_counts", 2025)
    assert t.num_rows == 26_612
    for c in DATASETS["snap_counts"].required:
        assert c in t.column_names


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
    import pyarrow.parquet as pq

    raw = config.RAW_DIR / "nflverse"
    files = list(raw.glob("*.parquet"))
    assert files, "no raw nflverse data present -- run pipeline.ingest.nflverse"
    banned = {"test", "placeholder", "mock", "dummy", "sample", "fake"}
    for f in files:
        t = pq.read_table(f).slice(0, 200)
        for name, col in zip(t.column_names, t.columns):
            if pa.types.is_string(col.type):
                vals = {str(v).lower() for v in col.to_pylist() if v is not None}
                assert not (vals & banned), f"placeholder value in {f.name}:{name}"
