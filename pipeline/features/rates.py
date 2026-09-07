"""Quarterback rates regress hard, and the projection was using them raw.

Reported from the board: Cam Ward, Tennessee's starter, projected at **0.9 passing
touchdowns** and driving a 98%-confident UNDER. He threw 15 in 595 attempts as a rookie
-- a 2.52% touchdown rate against a league average of 4.47% -- and the model reproduced
that rate exactly, because nothing regressed it.

The same omission ran the other way on the same board: Matthew Stafford at a 7.7% rate
projected 2.8 touchdowns a game, a 47.6-touchdown pace, above his own outlier season.

MEASURED over 77 quarterback season pairs, 2022-25, minimum 200 attempts:

    metric                  r      pool     best k    RMSE      unshrunk
    pass TD rate         +0.385   0.0447    0.35     0.01104    0.01375
    completion rate      +0.439   0.6156    0.35     0.02966    0.03853
    yards per completion +0.295  11.0589    0.25     0.85726    1.15939
    attempts per game    +0.489  33.7092    0.45     3.20257    3.88497

Every one of them is a weak signal -- the strongest explains 24% of next season -- and
every one was carried forward at full strength. Shrinking cuts error by a fifth to a
quarter on each. The effect on the two players above:

    Cam Ward          0.0252 -> 0.0378     0.88 -> ~1.3 TDs/game
    Matthew Stafford  0.0770 -> 0.0560     2.80 -> ~2.0 TDs/game

WHY A SAMPLE FLOOR. These priors are fitted on quarterbacks with 200+ attempts and mean
nothing for anyone else. A wide receiver has an `attempts_per_game` of zero, and
shrinking that toward 33.7 would hand him a starting quarterback's volume. Below the
floor the raw value is returned untouched.
"""
from __future__ import annotations

import numpy as np

#: metric -> (league pool value, fraction of the player's own deviation retained).
#: See the table above; fitted by `scripts/fit_qb_rates.py`.
QB_RATE_PRIOR: dict[str, tuple[float, float]] = {
    "pass_td_rate": (0.0447, 0.35),
    "completion_rate": (0.6156, 0.35),
    "yards_per_completion": (11.0589, 0.25),
    "attempts_per_game": (33.7092, 0.45),
}

#: (metric, position) -> (league pool, fraction of the player's own deviation kept).
#: Fitted the same way, on consecutive-season pairs with at least 40 targets or carries;
#: see `scripts/fit_skill_rates.py`.
#:
#:     catch rate       WR n=209 pool 0.6294 r=+0.442 k=0.45  RMSE 0.0717 (raw 0.0819)
#:                      TE n= 80 pool 0.7225 r=+0.154 k=0.15  RMSE 0.0610 (raw 0.0851)
#:                      RB n= 52 pool 0.7855 r=-0.090 k=0.00  RMSE 0.0626 (raw 0.0937)
#:     yards per catch  WR n=209 pool 12.958 r=+0.494 k=0.55  RMSE 2.1670 (raw 2.4152)
#:                      TE n= 80 pool 10.503 r=+0.400 k=0.45  RMSE 1.6604 (raw 1.8946)
#:                      RB n= 52 pool  7.479 r=+0.188 k=0.20  RMSE 1.4165 (raw 1.6903)
#:     yards per carry  RB n=160 pool  4.194 r=+0.102 k=0.10  RMSE 0.6981 (raw 0.9706)
#:                      QB n= 37 pool  4.821 r=+0.255 k=0.25  RMSE 1.1013 (raw 1.3985)
#:
#: A RUNNING BACK'S CATCH RATE FITS AT k = 0.00, and the correlation is NEGATIVE
#: (r = -0.090, n=52). Taken literally that says his own history is worse than knowing
#: nothing about him, and the league mean is the better estimate. The sample is small
#: and the true value is probably near zero rather than below it, but zero is what
#: minimises held-out error here (0.0626 against 0.0937 raw) and inventing a friendlier
#: number would be choosing a prior over a measurement.
#:
#: Yards per carry barely persists either: an RB keeps a tenth of his deviation, which
#: cuts error by 28%. Efficiency is mostly luck and blocking, and the model was treating
#: it as identity.
SKILL_RATE_PRIOR: dict[tuple[str, str], tuple[float, float]] = {
    ("catch_rate", "WR"): (0.6294, 0.45),
    ("catch_rate", "TE"): (0.7225, 0.15),
    ("catch_rate", "RB"): (0.7855, 0.00),
    ("yards_per_catch", "WR"): (12.9576, 0.55),
    ("yards_per_catch", "TE"): (10.5030, 0.45),
    ("yards_per_catch", "RB"): (7.4786, 0.20),
    ("yards_per_carry", "RB"): (4.1942, 0.10),
    ("yards_per_carry", "QB"): (4.8209, 0.25),
}

#: Targets or carries below which the skill priors do not apply.
MIN_TOUCHES = 40


def shrink_skill(
    value: float | None, metric: str, position: str | None, touches: int | float
) -> float | None:
    """Regress a skill rate toward its POSITION's pool. Unmeasured pair: raw."""
    if value is None or touches < MIN_TOUCHES:
        return value
    prior = SKILL_RATE_PRIOR.get((metric, (position or "").upper()))
    if prior is None:
        return value
    pool, k = prior
    return pool + (float(value) - pool) * k


def shrink_skill_samples(
    samples: np.ndarray, metric: str, position: str | None, touches: int | float
) -> np.ndarray:
    """Rescale an empirical draw so its mean regresses and its shape survives."""
    if samples is None or len(samples) == 0 or touches < MIN_TOUCHES:
        return samples
    if (metric, (position or "").upper()) not in SKILL_RATE_PRIOR:
        return samples
    raw_mean = float(np.mean(samples))
    if raw_mean <= 0:
        return samples
    target = shrink_skill(raw_mean, metric, position, touches)
    if target is None or target <= 0:
        return samples
    return samples * (target / raw_mean)


#: Below this many prior-season attempts the priors do not apply. They were fitted on
#: quarterbacks; everyone else must pass through untouched.
MIN_ATTEMPTS = 100


def shrink(value: float | None, metric: str, attempts: int | float) -> float | None:
    """Regress one rate toward its league pool. Unknown metric or thin sample: raw."""
    if value is None or attempts < MIN_ATTEMPTS:
        return value
    prior = QB_RATE_PRIOR.get(metric)
    if prior is None:
        return value
    pool, k = prior
    return pool + (float(value) - pool) * k


def shrink_samples(
    samples: np.ndarray, metric: str, attempts: int | float
) -> np.ndarray:
    """Regress an empirical draw by moving its MEAN, keeping its shape.

    The simulator bootstraps yards-per-completion from this player's own completions,
    which is the point -- his right tail is his. Replacing the array with a league one
    would throw that away, so it is rescaled instead: the spread and skew are his, the
    central tendency is regressed.
    """
    if samples is None or len(samples) == 0 or attempts < MIN_ATTEMPTS:
        return samples
    prior = QB_RATE_PRIOR.get(metric)
    if prior is None:
        return samples
    raw_mean = float(np.mean(samples))
    if raw_mean <= 0:
        return samples
    target = shrink(raw_mean, metric, attempts)
    if target is None or target <= 0:
        return samples
    return samples * (target / raw_mean)
