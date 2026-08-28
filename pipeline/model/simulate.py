"""Monte Carlo projection model (Section 7).

Deliberately simple and honest. A prop is a question about a distribution's TAIL, so
we simulate the distribution rather than producing a point estimate and pretending a
normal curve around it is the answer.

Structure, per Section 7:
  1. Project the volume driver first (targets, carries) including a P(inactive).
  2. Simulate volume, then outcome, drawing efficiency from the player's EMPIRICAL
     distribution -- receiving and rushing yards are strongly right-skewed and a
     normal assumption prices the tails wrong, which is where props live.
  3. Every adjustment is a NAMED, LOGGED multiplier so the Why panel can show the
     chain rather than a black box.

What this does NOT do: no gradient boosting, no learned interactions. Get a boring
model calibrated first (Section 7 closing note).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_ITERATIONS = 20_000


@dataclass
class Adjustment:
    """One named multiplier. The Why panel renders these in order."""
    name: str
    multiplier: float
    detail: str = ""


@dataclass
class VolumeProjection:
    """Expected opportunity for a player, before efficiency is applied."""
    player_id: str
    market: str
    baseline: float                     # e.g. trailing mean targets
    adjustments: list[Adjustment] = field(default_factory=list)
    p_inactive: float = 0.0             # discrete DNP probability
    dispersion: float = 1.0             # negative-binomial overdispersion (var/mean)

    @property
    def adjusted(self) -> float:
        v = self.baseline
        for a in self.adjustments:
            v *= a.multiplier
        return v

    def explain(self) -> list[dict]:
        """Ordered chain: baseline -> each multiplier -> final. Feeds the Why panel."""
        out, running = [{"step": "baseline", "value": self.baseline}], self.baseline
        for a in self.adjustments:
            running *= a.multiplier
            out.append({
                "step": a.name, "multiplier": a.multiplier,
                "value": running, "detail": a.detail,
            })
        return out


def _nb_params(mean: float, dispersion: float) -> tuple[float, float]:
    """Negative binomial (n, p) from a mean and a variance/mean ratio.

    Counts in football are overdispersed relative to Poisson: game script alone
    guarantees it. dispersion <= 1 collapses to Poisson-like behaviour.
    """
    if dispersion <= 1.0 or mean <= 0:
        return 0.0, 0.0
    var = mean * dispersion
    p = mean / var
    n = mean * p / (1.0 - p)
    return n, p


def simulate_volume(
    vp: VolumeProjection, rng: np.random.Generator, iterations: int
) -> np.ndarray:
    """Simulated opportunity counts, with inactive games as exact zeros."""
    mean = max(vp.adjusted, 0.0)
    n, p = _nb_params(mean, vp.dispersion)
    if n > 0:
        vol = rng.negative_binomial(n, p, size=iterations).astype(float)
    else:
        vol = rng.poisson(mean, size=iterations).astype(float)

    if vp.p_inactive > 0:
        # A DNP is the worst outcome for an over and must be modelled as a discrete
        # mass at zero, not smoothed into the volume distribution.
        vol = np.where(rng.random(iterations) < vp.p_inactive, 0.0, vol)
    return vol


def simulate_from_empirical(
    volume: np.ndarray,
    per_unit_samples: np.ndarray,
    rng: np.random.Generator,
    efficiency_multiplier: float = 1.0,
) -> np.ndarray:
    """Total = sum over `volume` draws from the player's empirical per-unit outcomes.

    Bootstrapping the player's own yards-per-catch / yards-per-carry preserves the
    fat right tail that a normal or gamma fit smooths away. That tail IS the prop.
    """
    if per_unit_samples.size == 0:
        return np.zeros_like(volume)

    iterations = volume.shape[0]
    max_v = int(volume.max()) if volume.max() > 0 else 0
    if max_v == 0:
        return np.zeros(iterations)

    # Draw a full matrix once, then mask by each iteration's volume: far faster than
    # looping, and the masked cells contribute nothing.
    draws = rng.choice(per_unit_samples, size=(iterations, max_v), replace=True)
    idx = np.arange(max_v)[None, :]
    mask = idx < volume[:, None]
    return (draws * mask).sum(axis=1) * efficiency_multiplier


def summarize(samples: np.ndarray, strikes: list[float]) -> dict:
    """Distribution summary plus P(over) at each strike.

    Kalshi prop markets settle on a strict 'more than' the strike, so P(over) uses
    a strict inequality. Using >= would systematically overprice every over.
    """
    pct = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    return {
        "mean": float(samples.mean()),
        "stdev": float(samples.std(ddof=1)) if samples.size > 1 else 0.0,
        "percentiles": {str(p): float(np.percentile(samples, p)) for p in pct},
        "p_over_by_strike": {
            str(s): float((samples > s).mean()) for s in strikes
        },
        "iterations": int(samples.size),
    }


def project_receiving_yards(
    vp: VolumeProjection,
    catch_rate: float,
    yards_per_catch_samples: np.ndarray,
    strikes: list[float],
    efficiency_multiplier: float = 1.0,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
) -> dict:
    """Targets -> catches (binomial) -> yards (empirical per catch)."""
    rng = np.random.default_rng(seed)
    targets = simulate_volume(vp, rng, iterations)
    catches = rng.binomial(targets.astype(int), np.clip(catch_rate, 0.0, 1.0))
    yards = simulate_from_empirical(
        catches.astype(float), yards_per_catch_samples, rng, efficiency_multiplier)
    out = summarize(yards, strikes)
    out["explain"] = vp.explain()
    out["mean_targets"] = float(targets.mean())
    out["mean_catches"] = float(catches.mean())
    return out


def project_receptions(
    vp: VolumeProjection,
    catch_rate: float,
    strikes: list[float],
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    targets = simulate_volume(vp, rng, iterations)
    catches = rng.binomial(targets.astype(int), np.clip(catch_rate, 0.0, 1.0))
    out = summarize(catches.astype(float), strikes)
    out["explain"] = vp.explain()
    out["mean_targets"] = float(targets.mean())
    return out


def project_rushing_yards(
    vp: VolumeProjection,
    yards_per_carry_samples: np.ndarray,
    strikes: list[float],
    efficiency_multiplier: float = 1.0,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
) -> dict:
    """Carries -> yards, drawing YPC empirically to keep the breakaway tail."""
    rng = np.random.default_rng(seed)
    carries = simulate_volume(vp, rng, iterations)
    yards = simulate_from_empirical(
        carries, yards_per_carry_samples, rng, efficiency_multiplier)
    out = summarize(yards, strikes)
    out["explain"] = vp.explain()
    out["mean_carries"] = float(carries.mean())
    return out
