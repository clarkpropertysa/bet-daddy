"""Parsing Kalshi event tickers, in ONE place.

A market ticker looks like `KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350`. Segment 1 is the
event -- two digits of year, a three-letter month, two digits of day, then the two team
codes concatenated with no separator.

That last part is the whole reason this module exists. The boundary between two
concatenated codes must be found by ANCHORING on a known code set, never by splitting at
the midpoint and never by subtracting one code from the string. Both shortcuts have
shipped bugs here:

- `"ARILV"` split at the midpoint gives `AR`/`ILV`; anchored it gives `ARI`/`LV`.
- `"SFLAR".replace("LA", "")` gives `"SFR"`, a team that does not exist. Because the
  crosswalk normalises LAR to LA, that silently disabled the opponent adjustment for the
  entire Rams franchise, all season, with no error.
- `"SFBPURDY13"` split greedily gives `SFB` + `PURDY` rather than `SF` + `BPURDY13`.

Three separate bug classes, one root cause. The regex had been reimplemented four times
across `project.py` alone before this module existed, so a fix in one copy left the others
wrong. Anything that needs to read an event ticker imports from here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Kalshi's own team codes. Deliberately a superset of nflverse's: Kalshi writes LAR and
# WSH where nflverse writes LA and WAS, and BOTH spellings appear in tickers. JAC is
# listed because it is a valid Kalshi spelling, NOT because nflverse uses it -- it does
# not, anywhere.
TEAM_CODES = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "JAC", "LA", "WSH",
})

# Kalshi code -> nflverse code. Applied on the way out, because every downstream
# consumer (defensive grades keyed on pbp `defteam`, the schedule join, Team.abbrev)
# speaks nflverse.
#
# Verified by comparing all 32 codes from live Kalshi game markets against
# schedules.parquet: Kalshi writes JAC and LAR, nflverse writes JAX and LA. Nothing
# else differs.
#
# The JAC entry used to be written JAX->JAC, exactly reversed. Kalshi's JAC therefore
# passed through untouched and never matched nflverse's JAX, so every Jacksonville
# player resolved UNRESOLVED and the projection skipped them in silence -- a whole
# franchise missing from the board with no error raised.
TO_NFLVERSE = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
)}

# Preseason months. Preseason snap distribution bears no relation to the regular season
# -- starters play a series or two -- so it is refused outright rather than left to a
# caller to remember.
PRESEASON_MONTHS = ("AUG", "JUL")

_EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})([A-Z]{4,8})$")


def split_matchup(teams: str) -> tuple[str, str] | None:
    """Split a concatenated matchup into (away, home) by anchoring on real codes.

    Longest first, so LAR is tried before LA and ARI before AR. Returns None rather than
    guessing when neither half is a known code -- a wrong split is far worse than no
    split, because it silently produces a plausible-looking team that never matches.
    """
    for away in sorted(TEAM_CODES, key=len, reverse=True):
        if teams.startswith(away):
            home = teams[len(away):]
            if home in TEAM_CODES:
                return away, home
    return None


@dataclass(frozen=True)
class Event:
    """A parsed event ticker. Team codes are NFLVERSE codes, already normalised."""
    date: str            # "2026-09-10"
    month: str           # "SEP"
    day: int
    away: str
    home: str
    raw_away: str        # Kalshi spelling, kept for round-tripping to Kalshi
    raw_home: str

    @property
    def label(self) -> str:
        """"SF at LA, Sep 10". A strike is meaningless without the game it belongs to."""
        return f"{self.raw_away} at {self.raw_home}, {self.month.title()} {self.day}"

    @property
    def is_preseason(self) -> bool:
        return self.month in PRESEASON_MONTHS


def parse_event(market_ticker: str) -> Event | None:
    """`KXNFLGAME-26SEP21NYGLAR-NYG` or a full prop ticker -> Event, or None.

    Accepts anything whose second dash-segment is an event ticker, so game markets and
    player-prop markets parse identically.
    """
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return None
    m = _EVENT_RE.match(parts[1])
    if not m:
        return None
    yy, mon, dd, teams = m.groups()
    if mon not in MONTHS:
        return None
    split = split_matchup(teams)
    if not split:
        return None
    raw_away, raw_home = split
    return Event(
        date=f"20{yy}-{MONTHS[mon]:02d}-{int(dd):02d}",
        month=mon,
        day=int(dd),
        away=TO_NFLVERSE.get(raw_away, raw_away),
        home=TO_NFLVERSE.get(raw_home, raw_home),
        raw_away=raw_away,
        raw_home=raw_home,
    )


def event_date(market_ticker: str) -> str | None:
    """`26SEP10SFLAR` -> "2026-09-10", the key rest context is stored under."""
    e = parse_event(market_ticker)
    return e.date if e else None


def opponent_of(market_ticker: str, team_code: str) -> str | None:
    """The other team in the event, as an nflverse code.

    `team_code` is expected to be an nflverse code too (that is what the crosswalk
    hands out), which is why comparison happens after normalisation.
    """
    if not team_code:
        return None
    e = parse_event(market_ticker)
    if not e:
        return None
    if team_code == e.away:
        return e.home
    if team_code == e.home:
        return e.away
    return None


def game_label(market_ticker: str) -> str | None:
    e = parse_event(market_ticker)
    return e.label if e else None


def is_preseason(market_ticker: str) -> bool:
    """True for a preseason event.

    Reads the month out of the ticker directly rather than requiring a full parse: a
    ticker whose team codes fail to split is still recognisably an August game, and
    refusing it is the safe outcome.
    """
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return False
    return any(mo in parts[1][:7].upper() for mo in PRESEASON_MONTHS)
