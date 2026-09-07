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
