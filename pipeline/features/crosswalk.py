"""Kalshi <-> nflverse player identity resolution.

Kalshi encodes the player in the market ticker as a STRUCTURED key, not a free-text
name: KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350 -> SF + B + PURDY + 13. That is far
stronger than fuzzy name matching, which Section 12 rightly warns against.

Measured on live markets (2026-08-28):
    naive regex (greedy team split)     55.1%   <- SFBPURDY13 parsed as SFB+PURDY
    team-anchored + alias map           92.3%
    + football_name initial fallback    93.8%

Two bugs worth remembering, both silent-failure classes:
  1. Team codes are 2-3 chars and ambiguous. A greedy regex turns SFBPURDY13 into
     SFB+PURDY. Must anchor on the known team set, longest code first.
  2. Legal first name != playing name. Matthew Stafford's nflverse first_name is
     "John". nflverse carries football_name for exactly this.

Nothing here silently guesses. Every resolution carries a method and confidence, and
unresolved keys are returned for review rather than dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import duckdb
import pyarrow as pa

# Kalshi team code -> nflverse team code. nflverse uses LA (not LAR), JAC (not JAX).
TEAM_ALIASES = {
    "LAR": "LA", "JAX": "JAC", "WSH": "WAS", "ARZ": "ARI",
    "CLV": "CLE", "HST": "HOU", "OAK": "LV", "SD": "LAC", "SL": "LA",
}

# Reviewed by hand. Keyed by raw Kalshi player key -> gsis_id.
# Every entry needs a comment saying why: an override without a reason is a bug
# waiting to be inherited.
MANUAL_OVERRIDES: dict[str, str] = {}

_KEY_RE = re.compile(r"^([A-Z.']+?)(\d{1,2})$")

RESULT_SCHEMA = pa.schema([
    ("raw_key", pa.string()), ("team", pa.string()),
    ("first_initial", pa.string()), ("surname", pa.string()),
    ("jersey", pa.int64()), ("gsis_id", pa.string()),
    ("full_name", pa.string()), ("position", pa.string()),
    ("method", pa.string()), ("confidence", pa.float64()),
])


class MatchMethod(str, Enum):
    EXACT = "EXACT"          # team + initial + surname + jersey
    FALLBACK = "FALLBACK"    # team + initial + surname (jersey ignored)
    MANUAL = "MANUAL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ParsedKey:
    raw: str
    team: str
    first_initial: str
    surname: str
    jersey: int


def parse_player_key(raw: str, valid_teams: set[str]) -> ParsedKey | None:
    """Split a Kalshi player key using the KNOWN team set, longest code first."""
    m = _KEY_RE.match(raw)
    if not m:
        return None
    body, jersey = m.group(1), int(m.group(2))
    for code in sorted(valid_teams, key=len, reverse=True):
        if body.startswith(code) and len(body) > len(code) + 1:
            rest = body[len(code):]
            return ParsedKey(raw, TEAM_ALIASES.get(code, code), rest[0], rest[1:], jersey)
    return None


def build_crosswalk(market_tickers: list[str], roster: pa.Table) -> pa.Table:
    """Resolve Kalshi player keys to gsis_ids. One row per distinct key."""
    con = duckdb.connect()
    con.register("roster_raw", roster)
    valid = {r[0] for r in con.execute(
        "select distinct team from roster_raw where team is not null").fetchall()}
    valid |= set(TEAM_ALIASES)

    seen: dict[str, ParsedKey] = {}
    for t in market_tickers:
        parts = t.split("-")
        if len(parts) < 3 or parts[2] in seen:
            continue
        if pk := parse_player_key(parts[2], valid):
            seen[parts[2]] = pk

    if not seen:
        return RESULT_SCHEMA.empty_table()

    keys = pa.Table.from_pylist(
        [{"raw_key": p.raw, "team": p.team, "first_initial": p.first_initial,
          "surname": p.surname, "jersey": p.jersey} for p in seen.values()],
        schema=pa.schema([("raw_key", pa.string()), ("team", pa.string()),
                          ("first_initial", pa.string()), ("surname", pa.string()),
                          ("jersey", pa.int64())]),
    )
    con.register("keys", keys)

    has_fb = "football_name" in roster.column_names
    fb_col = "football_name" if has_fb else "first_name"
    # position is optional: real rosters carry it, minimal test fixtures may not
    has_pos = "position" in roster.column_names
    pos_src = "position" if has_pos else "cast(null as varchar)"
    pos_sel = "r.position"

    # One row per (player, acceptable initial) so a single join covers both the legal
    # first name and the name the player actually goes by.
    con.execute(f"""
        create or replace temp view roster as
        select distinct
            team,
            cast(jersey_number as bigint) as jersey,
            full_name,
            gsis_id,
            upper(regexp_replace(last_name, '[^A-Za-z]', '', 'g')) as surname,
            upper(substr(initial_src, 1, 1)) as initial,
            position
        from (
            select team, jersey_number, full_name, last_name, gsis_id,
                   {pos_src} as position,
                   unnest([first_name, {fb_col}]) as initial_src
            from roster_raw
            where jersey_number is not null and gsis_id is not null
        )
    """)

    overrides = [{"raw_key": k, "gsis_id": v} for k, v in MANUAL_OVERRIDES.items()]
    con.register("overrides", pa.Table.from_pylist(
        overrides, schema=pa.schema([("raw_key", pa.string()), ("gsis_id", pa.string())])))

    return con.execute(f"""
        with exact as (
            select k.raw_key, r.gsis_id, r.full_name, {pos_sel}
            from keys k join roster r
              on r.team = k.team and r.jersey = k.jersey
             and r.surname = k.surname and r.initial = k.first_initial
        ),
        -- same team + name, jersey changed (mid-season number swaps happen)
        fallback as (
            select k.raw_key, r.gsis_id, r.full_name, {pos_sel}
            from keys k join roster r
              on r.team = k.team and r.surname = k.surname
             and r.initial = k.first_initial
            where k.raw_key not in (select raw_key from exact)
        ),
        resolved as (
            select raw_key, gsis_id, full_name, position,
                   '{MatchMethod.EXACT.value}' as method, 1.0 as confidence
            from (select *, row_number() over (partition by raw_key) rn from exact) where rn = 1
            union all
            select raw_key, gsis_id, full_name, position,
                   '{MatchMethod.FALLBACK.value}', 0.85
            from (select *, row_number() over (partition by raw_key) rn from fallback) where rn = 1
        )
        select
            k.raw_key, k.team, k.first_initial, k.surname, k.jersey,
            coalesce(r.gsis_id, o.gsis_id)            as gsis_id,
            r.full_name, r.position,
            case
                when r.method is not null then r.method
                when o.gsis_id is not null then '{MatchMethod.MANUAL.value}'
                else '{MatchMethod.UNRESOLVED.value}'
            end                                        as method,
            case
                when r.confidence is not null then r.confidence
                when o.gsis_id is not null then 1.0
                else 0.0
            end                                        as confidence
        from keys k
        left join resolved  r on r.raw_key = k.raw_key
        left join overrides o on o.raw_key = k.raw_key
    """).to_arrow_table().cast(RESULT_SCHEMA)
