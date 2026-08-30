"""Calibration: does a stated 60% actually happen 60% of the time?

Section 7.4. A model can be right on average and badly wrong in the tails, and props
live in the tails — so an uncalibrated model that looks accurate overall will still
lose money at the strikes people actually trade.

Two outputs:

  RELIABILITY  observed hit rate per predicted-probability bucket, with n and a
               Wilson interval. Wilson rather than normal because buckets are small
               and extreme -- a normal interval on 3 of 4 outcomes runs past 1.0.

  BRIER        mean squared error of the probability, decomposed into reliability
               (calibration error) and resolution (how much the model separates
               outcomes at all). A model can have a decent Brier score purely by
               predicting the base rate; resolution is what distinguishes it.

Isotonic regression fits a monotone correction from predicted to observed. It needs a
few hundred settled outcomes to be meaningful; below that it will happily overfit a
handful of points, so `fit_isotonic` refuses under a floor rather than returning a
curve that looks authoritative.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np

MIN_SAMPLES_FOR_ISOTONIC = 200
DEFAULT_BUCKETS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


@dataclass
class Bucket:
    lo: float
    hi: float
    n: int
    predicted: float
    observed: float
    ci_low: float
    ci_high: float


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Correct near 0 and 1, where normal intervals break."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def reliability(probs, outcomes, buckets=DEFAULT_BUCKETS) -> list[Bucket]:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    out: list[Bucket] = []
    for lo, hi in zip(buckets[:-1], buckets[1:]):
        m = (p >= lo) & (p < hi) if hi < 1.0 else (p >= lo) & (p <= hi)
        n = int(m.sum())
        if n == 0:
            continue
        k = int(y[m].sum())
        cl, ch = wilson(k, n)
        out.append(Bucket(lo, hi, n, float(p[m].mean()), k / n, cl, ch))
    return out


def brier(probs, outcomes) -> dict:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.size == 0:
        return {"brier": None, "n": 0}
    base = y.mean()
    score = float(((p - y) ** 2).mean())
    # Murphy decomposition against the same buckets used for reliability
    rel = res = 0.0
    for b in reliability(p, y):
        w = b.n / p.size
        rel += w * (b.predicted - b.observed) ** 2
        res += w * (b.observed - base) ** 2
    return {
        "brier": score,
        "reliability": rel,      # lower is better: calibration error
        "resolution": res,       # higher is better: does it separate outcomes
        "uncertainty": float(base * (1 - base)),
        "base_rate": float(base),
        "n": int(p.size),
        # a model that always predicts the base rate scores exactly `uncertainty`
        "skill_vs_base_rate": float(base * (1 - base) - score),
    }


def fit_isotonic(probs, outcomes):
    """Monotone predicted->observed correction, or None if the sample is too thin."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.size < MIN_SAMPLES_FOR_ISOTONIC:
        return None
    from sklearn.isotonic import IsotonicRegression

    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    ir.fit(p, y)
    return ir


def report(probs, outcomes) -> dict:
    b = brier(probs, outcomes)
    return {
        "brier": b,
        "buckets": [vars(x) for x in reliability(probs, outcomes)],
        "isotonic_fitted": fit_isotonic(probs, outcomes) is not None,
        "isotonic_min_samples": MIN_SAMPLES_FOR_ISOTONIC,
    }


def main():
    ap = argparse.ArgumentParser(description="Calibration report on graded signals")
    ap.add_argument("--model-version", default=None)
    a = ap.parse_args()

    import psycopg
    from pipeline.common import config

    where = 'where s."modelVersion" = %s' if a.model_version else ""
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        cur.execute(
            f'''select s."modelProb"::float8, r."settledResult", s.side,
                       coalesce((s.reason->>'implausible')::boolean, false)
                from "SignalResult" r join "Signal" s on s.id = r."signalId"
                {where} {"and" if a.model_version else "where"}
                r."settledResult" is not null''',
            (a.model_version,) if a.model_version else (),
        )
        rows = cur.fetchall()

    if not rows:
        print("no settled signals to calibrate")
        return

    # modelProb is the probability of the side TAKEN, so the outcome is whether that
    # side won -- not whether the market resolved YES.
    #
    # Reported twice. Implausible signals are hidden from the board by default and
    # would never be traded, so calibrating on them measures a model nobody uses.
    # But excluding them entirely would hide the model's worst failures, so both are
    # shown and the actionable set is the one that matters.
    def split(keep_implausible: bool):
        sel = [r for r in rows if keep_implausible or not r[3]]
        return ([r[0] for r in sel], [1.0 if r[1] == r[2] else 0.0 for r in sel])

    all_p, all_y = split(True)
    act_p, act_y = split(False)

    if act_p and len(act_p) != len(all_p):
        ab = brier(act_p, act_y)
        print(f"ACTIONABLE ONLY (implausible excluded): n={ab['n']}  "
              f"Brier {ab['brier']:.4f}  skill {ab['skill_vs_base_rate']:+.4f}")
        print()

    probs, outcomes = all_p, all_y
    rep = report(probs, outcomes)
    b = rep["brier"]
    print("ALL SIGNALS (including implausible):")
    print(f"n settled            : {b['n']}")
    print(f"base rate            : {b['base_rate']:.3f}")
    print(f"Brier score          : {b['brier']:.4f}  (lower better)")
    print(f"  reliability (cal)  : {b['reliability']:.4f}  (lower better)")
    print(f"  resolution         : {b['resolution']:.4f}  (higher better)")
    print(f"  skill vs base rate : {b['skill_vs_base_rate']:+.4f}")
    print()
    print(f"{'bucket':>12} {'n':>5} {'pred':>7} {'obs':>7}   95% CI")
    for x in rep["buckets"]:
        print(f"  {x['lo']:.1f}-{x['hi']:.1f} {x['n']:>8} {x['predicted']:>7.3f} "
              f"{x['observed']:>7.3f}   [{x['ci_low']:.2f}, {x['ci_high']:.2f}]")
    print()
    if rep["isotonic_fitted"]:
        print("isotonic correction fitted")
    else:
        print(f"isotonic NOT fitted: needs {rep['isotonic_min_samples']} settled "
              f"outcomes, have {b['n']}")


if __name__ == "__main__":
    main()
