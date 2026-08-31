"""Wind adjustment: banded, shrunk for forecast error, applied to both channels.

Measured over 1,186 outdoor team-games, 2022-25:

    wind      n     pass rate   yds/att   team pass yds
    0-4     263       0.577       6.74        235.0
    5-9     535       0.571       6.63        228.3
    10-14   270       0.570       6.48        223.1
    15-19    96       0.556       6.19        206.7
    20+      22       0.510       6.26        189.0

Monotonic in both channels. Wind above 20mph moves pass rate 6.7 points; the
spread-driven game script the model was built around moves it 2.2. Wind is roughly
three times larger, and unlike game script it also hits EFFICIENCY.

NOT A STADIUM CONFOUND. Demeaning each team against its own average, a club playing in
wind 6mph above its own norm passes 1.48pp less and throws for 19.7 fewer yards than
its own baseline (n=120, 32 teams). Weather is exogenous, which is more than can be
said for most inputs here.

WHY BANDS, NOT A SLOPE. The linear correlation is r = -0.079, which reads as nothing.
68% of outdoor games sit under 10mph, so a single coefficient averages the effect away
across games where there is no wind to speak of. The effect lives in a tail.

WHY THE COEFFICIENTS ARE SHRUNK. They were fitted on ACTUAL wind and are applied to a
FORECAST. Forecast error attenuates the real effect, and the attenuation grows with
lead time. `LEAD_SHRINK` is a deliberate under-application: being half-right about a
27-yard effect beats being confidently wrong about it.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Lower bound (mph) -> (pass-rate delta, efficiency multiplier).
#: Deltas are against the 0-9mph baseline, taken from the table above.
BANDS: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.000, 1.000),
    (10.0, -0.003, 0.978),   #  6.48 / 6.63
    (15.0, -0.017, 0.934),   #  6.19 / 6.63
    (20.0, -0.063, 0.944),   #  6.26 / 6.63 -- efficiency flattens, volume collapses
)

#: Below this, nothing is applied. Nearly every game sits here and pretending
#: otherwise would add noise to 68% of the slate.
MIN_ACTIONABLE_MPH = 10.0

#: Shrinkage by forecast lead time. A 10-day wind forecast is barely better than
#: climatology; a 12-hour one is good. Multiplies the band effect.
LEAD_SHRINK: tuple[tuple[float, float], ...] = (
    (24.0, 1.00),    # within a day: trust it
    (72.0, 0.80),    # three days
    (168.0, 0.55),   # a week
    (1e9, 0.35),     # beyond: directionally useful only
)


@dataclass(frozen=True)
class WindEffect:
    pass_rate_delta: float
    efficiency_multiplier: float
    wind_mph: float
    shrink: float
    band: str

    @property
    def is_material(self) -> bool:
        return self.pass_rate_delta != 0.0 or self.efficiency_multiplier != 1.0


NO_EFFECT = WindEffect(0.0, 1.0, 0.0, 1.0, "none")


def lead_shrink(lead_hours: float) -> float:
    for limit, factor in LEAD_SHRINK:
        if lead_hours <= limit:
            return factor
    return LEAD_SHRINK[-1][1]


def wind_effect(wind_mph: float | None, lead_hours: float = 0.0) -> WindEffect:
    """Banded effect on pass rate and passing efficiency.

    `None` means no forecast, which is NOT the same as calm and must produce no
    adjustment. A silent zero here would disable the layer exactly the way p_inactive
    and the spread were disabled, and look identical to a still day.
    """
    if wind_mph is None or wind_mph < MIN_ACTIONABLE_MPH:
        return NO_EFFECT

    lo, d_rate, eff = BANDS[0]
    for bound, delta, mult in BANDS:
        if wind_mph >= bound:
            lo, d_rate, eff = bound, delta, mult

    k = lead_shrink(lead_hours)
    return WindEffect(
        pass_rate_delta=d_rate * k,
        # Shrink toward 1.0, not toward 0.
        efficiency_multiplier=1.0 + (eff - 1.0) * k,
        wind_mph=float(wind_mph),
        shrink=k,
        band=f"{int(lo)}+ mph",
    )


def describe(e: WindEffect) -> str:
    """One line for the Why panel. Says the forecast AND its confidence."""
    if not e.is_material:
        return ""
    pct = abs(e.pass_rate_delta) * 100
    eff = (1.0 - e.efficiency_multiplier) * 100
    conf = "" if e.shrink >= 0.99 else f", shrunk to {e.shrink:.0%} for forecast lead"
    return (
        f"{e.wind_mph:.0f} mph forecast ({e.band}): pass rate -{pct:.1f}pts, "
        f"passing efficiency -{eff:.1f}%{conf}"
    )
