"""Pruning must delete only rows nothing reads, and never the ones the grader needs.

The selection runs on DuckDB here with the same SQL Postgres executes.
"""
import datetime as dt

import duckdb

from pipeline.model.prune import doomed_for_market, doomed_sql

NOW = dt.datetime(2026, 9, 10, 15, 0, tzinfo=dt.timezone.utc)
H = dt.timedelta(hours=1)
PAST = NOW - 20 * H            # a game that has kicked off
FUTURE = NOW + 50 * H          # a game that has not
R1, R2, R3 = NOW - 3 * H, NOW - 2 * H, NOW - 1 * H   # R3 is the newest run


def _db(rows, graded=()):
    con = duckdb.connect()
    con.execute('create table "Signal" (id varchar, "marketTicker" varchar, '
                '"runTs" timestamptz, kickoff timestamptz)')
    con.execute('create table "SignalResult" ("signalId" varchar)')
    con.executemany('insert into "Signal" values (?, ?, ?, ?)', rows)
    if graded:
        con.executemany('insert into "SignalResult" values (?)', [(g,) for g in graded])
    return con


def _doomed(con):
    return {r[0] for r in con.execute(doomed_sql("?"), [NOW]).fetchall()}


ROWS = [
    # A: future game priced in every run -> only the board's run survives
    ("a1", "A", R1, FUTURE), ("a2", "A", R2, FUTURE), ("a3", "A", R3, FUTURE),
    # B: future game the newest run REFUSED -> its last pre-kickoff signal survives,
    #    because the grader will score it
    ("b1", "B", R1, FUTURE), ("b2", "B", R2, FUTURE),
    # C: kicked off; two pre-game signals and two settled-mode re-emissions
    ("c1", "C", PAST - 3 * H, PAST), ("c2", "C", PAST - H, PAST),
    ("c3", "C", PAST + 2 * H, PAST), ("c4", "C", PAST + 5 * H, PAST),
    # D: graded on an older signal, then re-priced before kickoff
    ("d1", "D", PAST - 5 * H, PAST), ("d2", "D", PAST - 4 * H, PAST),
    ("d3", "D", PAST - 2 * H, PAST),
    # E: written before kickoff was stored -> newest one survives
    ("e1", "E", R1, None), ("e2", "E", R2, None),
]


def test_only_superseded_rows_go():
    con = _db(ROWS, graded=["d1"])
    assert _doomed(con) == {"a1", "a2", "b1", "c1", "c4", "d2", "e1"}


def test_the_grader_still_finds_its_row_for_every_market():
    """grade.py scores, per market, the last signal written before kickoff."""
    con = _db(ROWS, graded=["d1"])
    doomed = _doomed(con)
    last_pre = con.execute('''
        select distinct on ("marketTicker") id from "Signal"
        where kickoff is not null and "runTs" < kickoff
        order by "marketTicker", "runTs" desc''').fetchall()
    assert all(r[0] not in doomed for r in last_pre)


def test_every_ticker_keeps_a_row_so_settled_mode_does_not_reemit():
    con = _db(ROWS)
    doomed = _doomed(con)
    kept = {t for i, t, *_ in ROWS if i not in doomed}
    assert kept == {t for _, t, *_ in ROWS}


def test_the_board_run_is_untouched():
    con = _db(ROWS)
    assert not {"a3"} & _doomed(con)


def test_the_per_market_decision_matches_the_sql_it_replaces():
    """The SQL is the specification; `doomed_for_market` is what actually runs.

    Nothing scans the whole table on this database without the compute dropping the
    connection, so the rule is applied one market at a time in Python. Two
    implementations of one rule drift unless something pins them together.
    """
    con = _db(ROWS, graded=["d1"])
    board_ts = max(r[2] for r in ROWS if r[3] is not None and r[3] > NOW)
    by_ticker = {}
    for i, t, run_ts, kick in ROWS:
        by_ticker.setdefault(t, []).append((i, f"p{i}", run_ts, kick))

    got = {i for rows in by_ticker.values()
           for i, _ in doomed_for_market(rows, board_ts, {"d1"})}
    assert got == _doomed(con)


def test_the_projection_id_travels_with_its_signal():
    """`Signal."projectionId"` carries no index, so the orphan sweep that used it could
    not finish. Each doomed signal names its own projection instead."""
    rows = [("a1", "pa1", R1, FUTURE), ("a2", "pa2", R2, FUTURE),
            ("a3", "pa3", R3, FUTURE)]
    assert doomed_for_market(rows, R3, set()) == [("a1", "pa1"), ("a2", "pa2")]
