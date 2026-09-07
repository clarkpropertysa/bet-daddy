"""Replay 2025 week by week and score the model's probabilities against what happened.

WHAT THIS CAN AND CANNOT TEST. Kalshi retains no settled prop markets from 2025
(DECISIONS.md D1), so there are no historical lines and no way to reconstruct what the
model "would have bet". What CAN be tested is the thing that decides whether any bet is
profitable: when the model says 60%, does it happen 60% of the time?

An edge is `p_model - price`. If the probabilities are calibrated, a positive edge is
real money; if they are not, every edge on the board is noise however good the price
looks. Calibration is the precondition, and it needs no prices at all.

LEAK-FREE BY CONSTRUCTION. Week N is projected from `through_week=N`, which
`load_player_inputs` translates to `week < N`. Nothing from week N or later reaches the
inputs for week N.

THE BASELINE IS THE HONEST ONE. The model is compared against simply counting how often
the player has already cleared that line -- which is what its own rationale panel calls
"already in the price". Beating a coin flip is not the bar; beating the box score is.
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict

import duckdb
import numpy as np

from pipeline.model.features_for_projection import InsufficientHistory, load_player_inputs
from pipeline.model.simulate import (
    VolumeProjection,
    project_passing_tds,
    project_passing_yards,
    project_receiving_yards,
    project_receptions,
    project_rushing_yards,
)

PBP = "data/raw/nflverse/pbp_2025.parquet"
PLAYERS = "data/raw/nflverse/players.parquet"

# Kalshi-shaped ladders, so the strikes are the kind a market actually lists.
GRIDS = {
    "rec_yds":    [14.5, 24.5, 39.5, 49.5, 59.5, 69.5, 79.5, 89.5, 99.5],
    "rush_yds":   [14.5, 24.5, 39.5, 49.5, 59.5, 69.5, 79.5, 89.5, 99.5],
    "receptions": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5],
    "pass_yds":   [149.5, 174.5, 199.5, 224.5, 249.5, 274.5, 299.5, 324.5],
    "pass_tds":   [0.5, 1.5, 2.5, 3.5],
}


def weekly_actuals() -> dict:
    """(player, week) -> what actually happened. The scoring truth."""
    con = duckdb.connect()
    rows = con.execute(f"""
        with p as (
            select * from read_parquet('{PBP}')
            where season_type='REG' and coalesce(two_point_attempt,0)=0
        ),
        rec as (
            select receiver_player_id pid, week,
                   count(*) targets,
                   sum(coalesce(complete_pass,0)) receptions,
                   sum(case when complete_pass=1 then yards_gained else 0 end) rec_yds
            from p where play_type='pass' and receiver_player_id is not null
            group by 1,2
        ),
        rush as (
            select rusher_player_id pid, week, count(*) carries,
                   sum(yards_gained) rush_yds
            from p where rusher_player_id is not null group by 1,2
        ),
        pas as (
            select passer_player_id pid, week, count(*) att,
                   sum(case when complete_pass=1 then yards_gained else 0 end) pass_yds,
                   sum(coalesce(pass_touchdown,0)) pass_tds
            from p where play_type='pass' and passer_player_id is not null group by 1,2
        )
        select coalesce(r.pid,u.pid,s.pid) pid, coalesce(r.week,u.week,s.week) wk,
               coalesce(r.receptions,0), coalesce(r.rec_yds,0),
               coalesce(u.rush_yds,0), coalesce(s.pass_yds,0), coalesce(s.pass_tds,0)
        from rec r
        full outer join rush u on u.pid=r.pid and u.week=r.week
        full outer join pas s on s.pid=coalesce(r.pid,u.pid) and s.week=coalesce(r.week,u.week)
    """).fetchall()
    out = {}
    for pid, wk, rc, ry, ru, py, pt in rows:
        if pid is None or wk is None:
            continue
        out[(pid, int(wk))] = {
            "receptions": float(rc), "rec_yds": float(ry),
            "rush_yds": float(ru), "pass_yds": float(py), "pass_tds": float(pt),
        }
    return out


SNAPS = "data/raw/nflverse/snap_counts_2025.parquet"


def candidates(min_week: int) -> dict:
    """(market, player) -> every week he TOOK THE FIELD.

    NOT weeks in which he produced. Selecting on production is selecting on the
    outcome: it keeps the games where a receiver saw eight targets and drops the ones
    where he saw none, while the projection averages over both. Scored that way the
    model looks badly under-confident -- actual over-rates ran 5 to 9 points above
    predicted across every bucket -- and essentially all of that was the filter.

    A prop market is listed for a player expected to play, so "he played" is the
    honest condition, and it is knowable before kickoff.
    """
    con = duckdb.connect()
    played = con.execute(f"""
        with idmap as (
            select distinct pfr_id, gsis_id from read_parquet('{PLAYERS}')
            where pfr_id is not null and gsis_id is not null
        )
        select m.gsis_id, s.week
        from read_parquet('{SNAPS}') s
        join idmap m on m.pfr_id = s.pfr_player_id
        where s.game_type='REG' and coalesce(s.offense_snaps,0) > 0
    """).fetchall()

    # which market each player is even eligible for, from his season-long usage
    roles = con.execute(f"""
        with p as (select * from read_parquet('{PBP}')
                   where season_type='REG' and coalesce(two_point_attempt,0)=0)
        select 'rec' k, receiver_player_id pid, count(*) n
        from p where play_type='pass' and receiver_player_id is not null group by 1,2
        union all
        select 'rush', rusher_player_id, count(*) from p
        where rusher_player_id is not null group by 1,2
        union all
        select 'pass', passer_player_id, count(*) from p
        where play_type='pass' and passer_player_id is not null group by 1,2
    """).fetchall()
    eligible = defaultdict(set)
    for kind, pid, n in roles:
        if pid is None:
            continue
        # enough season-long usage that a book would list him at all
        if (kind == "rec" and n >= 40) or (kind == "rush" and n >= 40) \
                or (kind == "pass" and n >= 150):
            eligible[kind].add(pid)

    out = defaultdict(list)
    for pid, wk in played:
        if int(wk) < min_week:
            continue
        for kind in ("rec", "rush", "pass"):
            if pid in eligible[kind]:
                out[(kind, pid)].append(int(wk))
    return out


def positions() -> dict:
    return dict(duckdb.connect().execute(
        f"select gsis_id, position from read_parquet('{PLAYERS}') where gsis_id is not null"
    ).fetchall())


def empirical_p(hist: list[float], strike: float) -> float:
    """The baseline: how often has he already cleared this line?"""
    if not hist:
        return 0.5
    return sum(1 for v in hist if v > strike) / len(hist)


def brier(pairs):
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def calibration(pairs, bins=10):
    buckets = defaultdict(list)
    for p, o in pairs:
        buckets[min(int(p * bins), bins - 1)].append((p, o))
    rows = []
    for b in range(bins):
        g = buckets.get(b, [])
        if not g:
            continue
        rows.append((b / bins, (b + 1) / bins, len(g),
                     sum(p for p, _ in g) / len(g), sum(o for _, o in g) / len(g)))
    return rows


def _logit(p, eps=1e-6):
    p = min(max(p, eps), 1 - eps)
    return math.log(p / (1 - p))


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def fit_temperature(pairs) -> float:
    """One parameter: how far to shrink the log-odds toward an even chance.

    `a < 1` pulls every probability toward 0.5, which is the correction for
    over-confidence. A single parameter is deliberate -- an isotonic map with ten free
    buckets would fit this season's noise and carry none of it forward.
    """
    best, best_ll = 1.0, -1e18
    for i in range(20, 161):
        a = i / 100
        ll = 0.0
        for p, o in pairs:
            q = min(max(_sig(a * _logit(p)), 1e-9), 1 - 1e-9)
            ll += math.log(q) if o else math.log(1 - q)
        if ll > best_ll:
            best, best_ll = a, ll
    return best


def apply_temperature(p, a):
    return _sig(a * _logit(p))


def main():
    ap = argparse.ArgumentParser(description="Replay 2025 and score the probabilities")
    ap.add_argument("--from-week", type=int, default=8)
    ap.add_argument("--to-week", type=int, default=18)
    ap.add_argument("--iterations", type=int, default=4000)
    a = ap.parse_args()

    actual = weekly_actuals()
    cands = candidates(a.from_week)
    pos = positions()
    played_weeks: dict = defaultdict(set)
    for (kind, pid), weeks in cands.items():
        played_weeks[pid].update(weeks)

    model_pairs, base_pairs, weeks_of = [], [], []
    by_market = defaultdict(lambda: ([], []))
    skipped = defaultdict(int)
    hist: dict = defaultdict(list)

    # prior weeks per (player, metric), rebuilt as we walk forward
    for wk in range(a.from_week, a.to_week + 1):
        for (kind, pid), weeks in cands.items():
            if wk not in weeks:
                continue
            try:
                pi = load_player_inputs(PBP, pid, through_week=wk,
                                        position=pos.get(pid))
            except InsufficientHistory:
                skipped["insufficient_history"] += 1
                continue

            # He played, so a blank stat line is a genuine zero and must be scored.
            # Treating it as missing is the same selection bias one level down.
            zero = {"receptions": 0.0, "rec_yds": 0.0, "rush_yds": 0.0,
                    "pass_yds": 0.0, "pass_tds": 0.0}
            act = actual.get((pid, wk), zero)
            prior = [actual.get((pid, w), zero) for w in played_weeks.get(pid, set())
                     if w < wk]

            def score(market, out, key):
                got = act[key]
                h = [x[key] for x in prior]
                for s in GRIDS[market]:
                    p = out["p_over_by_strike"].get(str(s))
                    if p is None:
                        continue
                    hit = 1.0 if got > s else 0.0
                    model_pairs.append((p, hit))
                    weeks_of.append(wk)
                    base_pairs.append((empirical_p(h, s), hit))
                    by_market[market][0].append((p, hit))
                    by_market[market][1].append((empirical_p(h, s), hit))

            vp_kw = dict(adjustments=[], p_inactive=0.0)
            if kind == "rec":
                vp = VolumeProjection(pid, "rec_yds", pi.targets_per_game,
                                      dispersion=pi.target_dispersion, **vp_kw)
                score("rec_yds", project_receiving_yards(
                    vp, pi.catch_rate, pi.yards_per_catch, GRIDS["rec_yds"],
                    iterations=a.iterations, seed=wk), "rec_yds")
                score("receptions", project_receptions(
                    vp, pi.catch_rate, GRIDS["receptions"],
                    iterations=a.iterations, seed=wk), "receptions")
            elif kind == "rush":
                vp = VolumeProjection(pid, "rush_yds", pi.carries_per_game,
                                      dispersion=pi.carry_dispersion, **vp_kw)
                score("rush_yds", project_rushing_yards(
                    vp, pi.yards_per_carry, GRIDS["rush_yds"],
                    iterations=a.iterations, seed=wk), "rush_yds")
            else:
                vp = VolumeProjection(pid, "pass_yds", pi.attempts_per_game,
                                      dispersion=pi.attempt_dispersion, **vp_kw)
                score("pass_yds", project_passing_yards(
                    vp, pi.completion_rate, pi.yards_per_completion, GRIDS["pass_yds"],
                    iterations=a.iterations, seed=wk), "pass_yds")
                score("pass_tds", project_passing_tds(
                    vp, pi.pass_td_rate, GRIDS["pass_tds"],
                    iterations=a.iterations, seed=wk), "pass_tds")

    n = len(model_pairs)
    print(f"2025 replay, weeks {a.from_week}-{a.to_week}, leak-free (through_week=N)\n")
    print(f"scored predictions: {n:,}")
    if skipped:
        print("skipped:", dict(skipped))
    if not n:
        return
    bm, bb = brier(model_pairs), brier(base_pairs)
    print(f"\nBrier score (lower is better)")
    print(f"  model                 {bm:.4f}")
    print(f"  his own hit rate      {bb:.4f}")
    print(f"  always 50%            {brier([(0.5, o) for _, o in model_pairs]):.4f}")
    print(f"  base rate             "
          f"{brier([(sum(o for _, o in model_pairs)/n, o) for _, o in model_pairs]):.4f}")
    print(f"  skill vs box score    {(bb - bm) / bb:+.1%}")

    print(f"\ncalibration (model)")
    print(f"  {'bucket':12} {'n':>7} {'predicted':>10} {'actual':>8}  gap")
    for lo, hi, cnt, pred, obs in calibration(model_pairs):
        print(f"  {f'{lo:.1f}-{hi:.1f}':12} {cnt:7,} {pred:10.3f} {obs:8.3f}  {obs-pred:+.3f}")

    # --- does a calibration correction survive out of sample? --------------------
    # Fitted on the FIRST weeks and scored on the LAST, so the number below is a
    # held-out result rather than the same data twice.
    mid = a.from_week + (a.to_week - a.from_week) // 2
    train = [(p, o) for (p, o), w in zip(model_pairs, weeks_of) if w <= mid]
    test = [(p, o) for (p, o), w in zip(model_pairs, weeks_of) if w > mid]
    if train and test:
        t = fit_temperature(train)
        raw = brier(test)
        cal = brier([(apply_temperature(p, t), o) for p, o in test])
        print(f"\ncalibration correction (fit weeks {a.from_week}-{mid}, "
              f"tested {mid+1}-{a.to_week})")
        print(f"  temperature           {t:.2f}   (<1 shrinks toward 50%)")
        print(f"  held-out Brier raw    {raw:.4f}")
        print(f"  held-out Brier fixed  {cal:.4f}")
        print(f"  improvement           {(raw - cal) / raw:+.2%}")
        print(f"\n  held-out calibration BEFORE correction")
        print(f"  {'bucket':12} {'n':>7} {'predicted':>10} {'actual':>8}  gap")
        for lo, hi, cnt, pred, obs in calibration(test):
            print(f"  {f'{lo:.1f}-{hi:.1f}':12} {cnt:7,} {pred:10.3f} "
                  f"{obs:8.3f}  {obs-pred:+.3f}")
        print(f"\n  held-out calibration after correction")
        print(f"  {'bucket':12} {'n':>7} {'predicted':>10} {'actual':>8}  gap")
        for lo, hi, cnt, pred, obs in calibration(
                [(apply_temperature(p, t), o) for p, o in test]):
            print(f"  {f'{lo:.1f}-{hi:.1f}':12} {cnt:7,} {pred:10.3f} "
                  f"{obs:8.3f}  {obs-pred:+.3f}")

    # A one-sided correction: the board's exposure is high-confidence picks, and the
    # low end is if anything slightly UNDER-confident, so a symmetric shrink cannot
    # fix both. Fitted and tested on the same split.
    if train and test:
        hi_train = [(p, o) for p, o in train if p > 0.5]
        if hi_train:
            th = fit_temperature(hi_train)
            def one_sided(p, a=th):
                return apply_temperature(p, a) if p > 0.5 else p
            cal2 = brier([(one_sided(p), o) for p, o in test])
            print(f"\none-sided correction (applied only above 50%)")
            print(f"  temperature           {th:.2f}")
            print(f"  held-out Brier raw    {raw:.4f}")
            print(f"  held-out Brier fixed  {cal2:.4f}")
            print(f"  improvement           {(raw - cal2) / raw:+.2%}")
            hi_test = [(p, o) for p, o in test if p > 0.5]
            if hi_test:
                rh = brier(hi_test)
                ch = brier([(one_sided(p), o) for p, o in hi_test])
                print(f"  on the >50% rows only: {rh:.4f} -> {ch:.4f} "
                      f"({(rh-ch)/rh:+.2%}, n={len(hi_test):,})")

    print(f"\nby market")
    print(f"  {'market':12} {'n':>7} {'model':>8} {'box score':>10}  skill")
    for mk in sorted(by_market):
        mp, bp = by_market[mk]
        m, b = brier(mp), brier(bp)
        print(f"  {mk:12} {len(mp):7,} {m:8.4f} {b:10.4f}  {(b-m)/b:+.1%}")


if __name__ == "__main__":
    main()
