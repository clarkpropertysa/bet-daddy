"""Backups must not be projected.

J.J. McCarthy started for Minnesota in 2025 and is QB2 behind Kyler Murray in 2026.
His 27 attempts-per-game baseline describes a job he no longer has, so projecting it
produces a confident number about a player who may not take a snap. Before this gate
existed, 105 of 158 skippable markets were backup quarterbacks.
"""
import duckdb
import pytest

from pipeline.model.project import STARTER_DEPTH, _starters

pytestmark = pytest.mark.network

DEPTH = "data/raw/nflverse/depth_charts_2026.parquet"


@pytest.fixture(scope="module")
def depth():
    return _starters(DEPTH)


def test_uses_only_the_latest_depth_snapshot(depth):
    """The 2026 file holds ~160 dated snapshots back to March. Taking them all
    returns a player at every rank he has ever held."""
    n_dates = duckdb.connect().execute(
        f"select count(distinct dt) from read_parquet('{DEPTH}')").fetchone()[0]
    assert n_dates > 50
    # one entry per player-position, not one per snapshot
    assert len(depth) < 4000


def test_murray_is_minnesotas_starter_and_mccarthy_is_not(depth):
    """The specific case that exposed the missing filter."""
    murray = [g for g, (p, r) in depth.items() if p == "QB" and r == 1]
    con = duckdb.connect()
    names = dict(con.execute(f"""
        with latest as (select max(dt) m from read_parquet('{DEPTH}'))
        select gsis_id, player_name from read_parquet('{DEPTH}'), latest
        where dt = latest.m and team = 'MIN' and pos_abb = 'QB'
    """).fetchall())
    ranks = {names[g]: depth[g][1] for g in names if g in depth}
    assert ranks.get("Kyler Murray") == 1
    assert ranks.get("J.J. McCarthy", 99) > 1


def test_starter_depth_covers_the_priceable_positions():
    assert STARTER_DEPTH == {"QB": 1, "RB": 2, "WR": 3, "TE": 1}


def test_every_team_has_exactly_one_qb1(depth):
    con = duckdb.connect()
    rows = con.execute(f"""
        with latest as (select max(dt) m from read_parquet('{DEPTH}'))
        select team, count(*) from read_parquet('{DEPTH}'), latest
        where dt = latest.m and pos_abb = 'QB' and pos_rank = 1
        group by 1
    """).fetchall()
    assert len(rows) == 32
    assert all(n == 1 for _, n in rows)
