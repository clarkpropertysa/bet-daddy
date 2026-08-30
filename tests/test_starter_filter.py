"""Who is actually starting, and the promotion rule.

Two bugs this pins:

1. The board showed J.J. McCarthy passing props. He started for Minnesota in 2025 and
   is QB2 behind Kyler Murray in 2026. `isStarter` was computed correctly and the
   projection job never consulted it.
2. The projection job then reimplemented the rule WITHOUT injury promotion, so a
   backup promoted by a starter's absence would have been refused -- the exact
   signal Section 5.2 calls most exploitable.

Both callers now share `features/starters.py`.
"""
import duckdb
import pytest

from pipeline.features.starters import (
    OUT_STATUSES,
    STARTER_DEPTH,
    latest_depth,
    resolve_starters,
)

pytestmark = pytest.mark.network

DEPTH = "data/raw/nflverse/depth_charts_2026.parquet"


@pytest.fixture(scope="module")
def starters():
    return resolve_starters(DEPTH)


def test_uses_only_the_latest_depth_snapshot():
    """The 2026 file holds ~160 dated snapshots back to March. Taking them all
    returns a player at every rank he has ever held."""
    n_dates = duckdb.connect().execute(
        f"select count(distinct dt) from read_parquet('{DEPTH}')").fetchone()[0]
    assert n_dates > 50
    rows = latest_depth(DEPTH)
    ids = [r[1] for r in rows]
    assert len(ids) == len(set(ids)) or len(rows) < 2000


def test_murray_starts_for_minnesota_and_mccarthy_does_not(starters):
    """The specific case that exposed the missing filter."""
    names = dict(duckdb.connect().execute(f"""
        with latest as (select max(dt) m from read_parquet('{DEPTH}'))
        select gsis_id, player_name from read_parquet('{DEPTH}'), latest
        where dt = latest.m and team = 'MIN' and pos_abb = 'QB'
    """).fetchall())
    starting = {names[g] for g in names if g in starters}
    assert "Kyler Murray" in starting
    assert "J.J. McCarthy" not in starting


def test_starter_depth_covers_the_priceable_positions():
    assert STARTER_DEPTH == {"QB": 1, "RB": 2, "WR": 3, "TE": 1}


def test_one_starter_per_team_at_qb(starters):
    qbs: dict[str, int] = {}
    for s in starters.values():
        if s.position == "QB":
            qbs[s.team] = qbs.get(s.team, 0) + 1
    assert len(qbs) == 32
    assert all(n == 1 for n in qbs.values())


def test_nobody_is_promoted_when_there_are_no_injuries(starters):
    assert all(s.promoted_for is None for s in starters.values())


def test_an_out_starter_promotes_his_backup(tmp_path):
    """The behaviour the projection job previously lacked: when QB1 is ruled out,
    QB2 becomes projectable and is labelled with whose absence put him there."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    qb1, qb2 = "00-0000001", "00-0000002"
    depth = pa.table({
        "dt": ["2026-08-27"] * 2,
        "team": ["MIN"] * 2,
        "gsis_id": [qb1, qb2],
        "player_name": ["Starter Guy", "Backup Guy"],
        "pos_abb": ["QB", "QB"],
        "pos_rank": [1, 2],
    })
    dp = tmp_path / "depth.parquet"
    pq.write_table(depth, dp)

    inj = pa.table({"gsis_id": [qb1], "report_status": ["Out"]})
    ip = tmp_path / "inj.parquet"
    pq.write_table(inj, ip)

    healthy = resolve_starters(str(dp))
    assert qb1 in healthy and qb2 not in healthy

    injured = resolve_starters(str(dp), str(ip))
    assert qb2 in injured, "backup must be projectable once the starter is out"
    assert qb1 not in injured
    assert injured[qb2].promoted_for == "Starter Guy"


def test_doubtful_also_frees_the_slot():
    assert "Doubtful" in OUT_STATUSES and "Out" in OUT_STATUSES
