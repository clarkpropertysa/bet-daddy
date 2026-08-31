"""Wind forecasts for outdoor games, from Open-Meteo.

nflverse ships `temp` and `wind` in schedules.parquet, but backfills them AFTER the
game: 2025 is fully populated and 2026 is 0 of 272. That is useless for pricing a
market before kickoff, which is the only time it matters.

Open-Meteo needs no API key, allows this use, and returns a 16-day hourly forecast --
comfortably longer than the window in which these markets are quoted. Verified live
against the Week 1 opener at Lumen Field: 6.4mph, 62.5F.

TWO FAILURE MODES THIS MODULE EXISTS TO AVOID:

1. **A failed fetch must not read as calm.** Returning 0mph on error is indistinguishable
   from a still day and would silently disable the adjustment. Every failure returns
   None, and the caller applies nothing.
2. **A dome must not get a wind adjustment.** `roof` already distinguishes them, and a
   retractable roof that is closed is a dome for this purpose.

The forecast is a FORECAST. Lead time is returned with it so the caller can shrink the
adjustment as the horizon lengthens, and so the attenuation becomes measurable later
rather than assumed now.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

API = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 20

#: Roof values that mean the game is exposed to weather. A closed retractable roof is
#: not, and nflverse distinguishes "closed" from "open" precisely so this works.
OUTDOOR_ROOFS = ("outdoors", "open")

#: Stadium coordinates, keyed by nflverse `stadium_id`. Hand-verified.
#: A missing key returns no forecast rather than a guess -- a neutral-site game at the
#: wrong coordinates would be worse than no adjustment at all.
STADIUM_COORDS: dict[str, tuple[float, float]] = {
    # Domes and fixed/closed roofs are listed for completeness but never fetched --
    # is_outdoor() gates on `roof`, not on this table.
    "ATL97": (33.7554, -84.4008),    # Mercedes-Benz
    "BAL00": (39.2780, -76.6227),    # M&T Bank
    "BOS00": (42.0909, -71.2643),    # Gillette
    "BUF00": (42.7738, -78.7870),    # Highmark
    "CAR00": (35.2258, -80.8528),    # Bank of America
    "CHI98": (41.8623, -87.6167),    # Soldier Field
    "CIN00": (39.0955, -84.5161),    # Paycor
    "CLE00": (41.5061, -81.6995),    # Huntington Bank Field
    "DAL00": (32.7473, -97.0945),    # AT&T
    "DEN00": (39.7439, -105.0201),   # Empower Field
    "DET00": (42.3400, -83.0456),    # Ford Field
    "GNB00": (44.5013, -88.0622),    # Lambeau
    "HOU00": (29.6847, -95.4107),    # NRG
    "IND00": (39.7601, -86.1639),    # Lucas Oil
    "JAX00": (30.3239, -81.6373),    # EverBank
    "KAN00": (39.0489, -94.4839),    # Arrowhead
    "LAX01": (33.9535, -118.3392),   # SoFi
    "MIA00": (25.9580, -80.2389),    # Hard Rock
    "MIN01": (44.9738, -93.2578),    # U.S. Bank
    "NAS00": (36.1665, -86.7713),    # Nissan
    "NOR00": (29.9511, -90.0812),    # Caesars Superdome
    "NYC01": (40.8135, -74.0745),    # MetLife
    "PHI00": (39.9008, -75.1675),    # Lincoln Financial
    "PHO00": (33.5276, -112.2626),   # State Farm
    "PIT00": (40.4468, -80.0158),    # Acrisure
    "SEA00": (47.5952, -122.3316),   # Lumen
    "SFO01": (37.4033, -121.9694),   # Levi's
    "TAM00": (27.9759, -82.5033),    # Raymond James
    "VEG00": (36.0909, -115.1833),   # Allegiant
    "WAS00": (38.9077, -76.8645),    # Northwest
    # International venues. Outdoor ones genuinely need these -- a London or Mexico
    # City game priced with no wind adjustment is the same silent gap as a dome
    # priced with one.
    "LON00": (51.5560, -0.2795),     # Wembley (outdoors)
    "LON02": (51.6043, -0.0665),     # Tottenham Hotspur (outdoors)
    "MEX00": (19.3029, -99.1505),    # Estadio Banorte (outdoors)
    "SAO00": (-23.5453, -46.4742),   # Arena Corinthians (outdoors)
    "GER00": (48.2188, 11.6247),     # Allianz Arena (outdoors)
    "MAD01": (40.4531, -3.6883),     # Bernabeu
    "MEL00": (-37.8200, 144.9834),   # Melbourne Cricket Ground
    "MUN01": (48.2188, 11.6247),     # FC Bayern Munich Stadium
    "PAR00": (48.9245, 2.3601),      # Stade de France
    "RIO00": (-22.9121, -43.2302),   # Maracana
}


@dataclass(frozen=True)
class Forecast:
    wind_mph: float
    temp_f: float | None
    precip_in: float | None
    #: Hours between the forecast being taken and kickoff. A 10-day-out wind number is
    #: far less reliable than a 1-day-out one, and the caller shrinks accordingly.
    lead_hours: float
    source: str = "open-meteo"


def is_outdoor(roof: str | None) -> bool:
    return (roof or "").strip().lower() in OUTDOOR_ROOFS


def fetch_forecast(
    lat: float, lon: float, kickoff_utc: datetime, session: requests.Session | None = None
) -> Forecast | None:
    """Hourly forecast nearest kickoff, or None. Never raises.

    None means "no adjustment", never "calm". Those must stay distinguishable: a
    silent zero would disable the layer exactly as p_inactive and the spread were
    disabled, and look identical to a still day.
    """
    get = (session or requests).get
    try:
        r = get(
            API,
            params={
                "latitude": lat, "longitude": lon,
                "hourly": "wind_speed_10m,temperature_2m,precipitation",
                "wind_speed_unit": "mph", "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "forecast_days": 16, "timezone": "UTC",
            },
            headers={"User-Agent": "bet-daddy/0.1 (personal research)"},
            timeout=TIMEOUT,
        )
        if not r.ok:
            return None
        h = r.json().get("hourly") or {}
        times = h.get("time") or []
        winds = h.get("wind_speed_10m") or []
        if not times or len(winds) != len(times):
            return None
    except Exception:
        return None

    target = kickoff_utc.astimezone(timezone.utc).replace(tzinfo=None)
    best_i, best_gap = None, None
    for i, t in enumerate(times):
        try:
            ts = datetime.fromisoformat(t)
        except ValueError:
            continue
        gap = abs((ts - target).total_seconds())
        if best_gap is None or gap < best_gap:
            best_i, best_gap = i, gap

    # Beyond the forecast horizon the nearest hour can be days away; that is not a
    # forecast for this game.
    if best_i is None or best_gap is None or best_gap > 6 * 3600:
        return None
    if winds[best_i] is None:
        return None

    temps = h.get("temperature_2m") or []
    precip = h.get("precipitation") or []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return Forecast(
        wind_mph=float(winds[best_i]),
        temp_f=float(temps[best_i]) if best_i < len(temps) and temps[best_i] is not None else None,
        precip_in=float(precip[best_i]) if best_i < len(precip) and precip[best_i] is not None else None,
        lead_hours=max((target - now).total_seconds() / 3600.0, 0.0),
    )


def forecast_for_game(
    stadium_id: str | None,
    roof: str | None,
    kickoff_utc: datetime | None,
    session: requests.Session | None = None,
) -> Forecast | None:
    """None for a dome, an unknown stadium, or any failure."""
    if not is_outdoor(roof) or not stadium_id or kickoff_utc is None:
        return None
    coords = STADIUM_COORDS.get(stadium_id)
    if coords is None:
        return None
    return fetch_forecast(coords[0], coords[1], kickoff_utc, session=session)
