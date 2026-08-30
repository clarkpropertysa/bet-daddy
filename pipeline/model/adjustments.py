"""Named, data-derived multipliers applied to a volume baseline.

Every adjustment is (a) named, (b) logged, and (c) shown in the Why panel, so it can
be argued with rather than trusted. Section 7 requires exactly this.

CALIBRATION CAVEAT, stated plainly: the SHAPE of each adjustment comes from data (a
defense's EPA allowed relative to league average, a team's actual rest state), but
the SCALE -- how much a one-sigma defense should move a projection -- is a prior, not
a fitted parameter. It cannot be fitted yet: that needs forward CLV across a few
hundred settled contracts, which is precisely what the archive is accumulating.

The scales are therefore deliberately SMALL. An uncalibrated multiplier that is too
large manufactures edge; one that is too small merely fails to find some. Given the
fee floor, the second error is much cheaper than the first.
"""
from __future__ import annotations

import duckdb

from pipeline.model.simulate import Adjustment

# Max proportional swing from an extreme (±2σ) opponent. 8% on volume is modest by
# design -- see the calibration caveat above.
DEFENSE_MAX_SWING = 0.08

# Rest effects on VOLUME are small and poorly evidenced in public data; the large
# documented rest effects are on efficiency and availability, not opportunity.
SHORT_WEEK_SWING = 0.03
POST_BYE_SWING = 0.02

# Recent usage carries real information, but a three-game sample is noisy. The raw
# trend is shrunk toward zero by the sample size and then capped: a player whose last
# three games are 40% above his season rate moves the projection by at most 10%.
USAGE_TREND_MAX_SWING = 0.10
USAGE_TREND_FULL_WEIGHT_GAMES = 5

# Which defensive split governs which market.
MARKET_TO_DEFENSE = {
    "rec_yds": ("pass", "all"),
    "receptions": ("pass", "all"),
    "pass_yds": ("pass", "all"),
    "pass_tds": ("pass", "all"),
    "rush_yds": ("rush", "all"),
}


def defense_adjustment(
    opponent: str,
    market_type: str,
    pass_grades,
    rush_grades,
) -> Adjustment | None:
    """Opponent strength as a bounded multiplier, from EPA allowed vs league mean.

    A defense one standard deviation worse than average raises the projection by
    half the max swing; ±2σ saturates. Saturation matters: without it a single
    outlier defense produces an unbounded multiplier off a thin sample.
    """
    side = MARKET_TO_DEFENSE.get(market_type)
    if side is None:
        return None
    kind, _ = side
    grades = pass_grades if kind == "pass" else rush_grades

    con = duckdb.connect()
    con.register("g", grades)
    metric = "epa_per_target" if kind == "pass" else "epa_per_carry"
    where = ("where rankable" if kind == "pass"
             else "where rankable and run_location = 'all'")

    row = con.execute(f"""
        with agg as (
            select team, avg({metric}) as epa from g {where} group by team
        ),
        stats as (select avg(epa) m, stddev_samp(epa) s from agg)
        select a.epa, s.m, s.s from agg a, stats s where a.team = ?
    """, [opponent]).fetchone()

    if not row or row[2] in (None, 0):
        return None
    epa, mean, sd = row
    z = max(-2.0, min(2.0, (epa - mean) / sd))
    mult = 1.0 + (z / 2.0) * DEFENSE_MAX_SWING
    return Adjustment(
        name="opponent_defense",
        multiplier=round(mult, 4),
        detail=f"{opponent} {kind} D at {z:+.2f}σ EPA allowed",
    )


def rest_adjustment(days_rest: int | None, is_short_week: bool,
                    is_post_bye: bool) -> Adjustment | None:
    """Rest state as a small volume multiplier."""
    if is_short_week:
        return Adjustment("short_week", 1.0 - SHORT_WEEK_SWING,
                          f"{days_rest} days rest")
    if is_post_bye:
        return Adjustment("post_bye", 1.0 + POST_BYE_SWING,
                          f"{days_rest} days rest")
    return None


def usage_trend_adjustment(
    recent_mean: float | None,
    season_mean: float | None,
    recent_games: int,
) -> Adjustment | None:
    """Recent opportunity against the season rate, shrunk by sample size.

    Volume is the input props are most sensitive to, and a role change shows up here
    before it shows up anywhere else. But three games is thin, so the raw trend is
    weighted by how many games it rests on and then capped -- an uncapped trend on a
    two-game sample would swamp every other adjustment.
    """
    if not season_mean or recent_mean is None or recent_games < 2:
        return None
    raw = (recent_mean - season_mean) / season_mean
    weight = min(recent_games / USAGE_TREND_FULL_WEIGHT_GAMES, 1.0)
    # Clamp BEFORE shrinking. Shrinking first and capping after means any trend
    # large enough to hit the cap arrives at the cap regardless of sample size, so
    # a two-game streak moves the projection exactly as much as an eight-game one
    # and the shrinkage silently does nothing.
    capped = max(-USAGE_TREND_MAX_SWING, min(USAGE_TREND_MAX_SWING, raw))
    swing = capped * weight
    if abs(swing) < 0.005:
        return None
    direction = "above" if raw > 0 else "below"
    return Adjustment(
        name="usage_trend",
        multiplier=round(1.0 + swing, 4),
        detail=(f"last {recent_games} games {abs(raw):.0%} {direction} his season rate"
                f" (shrunk to {abs(swing):.1%} on {recent_games} games)"),
    )
