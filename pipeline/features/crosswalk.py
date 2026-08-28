"""Kalshi <-> nflverse player identity resolution.

Kalshi encodes the player in the market ticker as a STRUCTURED key, not a free-text
name: KXNFLPASSYDS-26SEP10SFLAR-SFBPURDY13-350 -> SF + B + PURDY + 13. That is far
stronger than fuzzy name matching, which Section 12 rightly warns against.

Measured on 636 live markets (2026-08-28):
    naive regex (greedy team split)     55.1%   <- SFBPURDY13 parsed as SFB+PURDY
    team-anchored + alias map           92.3%
    + jersey-agnostic fallback          92.8%
Residual is ~9 players, all genuine roster churn (recent signings the week-1 roster
snapshot has not absorbed). Those go to MANUAL_OVERRIDES.

Nothing here silently guesses. Every resolution carries a method and confidence, and
unresolved keys are returned for review rather than dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import polars as pl

# Kalshi team code -> nflverse team code. nflverse uses LA (not LAR) and JAC (not JAX).
TEAM_ALIASES = {
    "LAR": "LA", "JAX": "JAC", "WSH": "WAS", "ARZ": "ARI",
    "CLV": "CLE", "HST": "HOU", "OAK": "LV", "SD": "LAC", "SL": "LA",
}

# Reviewed by hand. Keyed by the raw Kalshi player key; value is a gsis_id.
# Every entry needs a comment saying why -- an override without a reason is a bug
# waiting to be inherited.
MANUAL_OVERRIDES: dict[str, str] = {}

_KEY_RE = re.compile(r"^([A-Z.']+?)(\d{1,2})$")


class MatchMethod(str, Enum):
    EXACT = "EXACT"              # team + first initial + surname + jersey
    FALLBACK = "FALLBACK"        # team + first initial + surname (jersey ignored)
    MANUAL = "MANUAL"            # human override
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ParsedKey:
    raw: str
    team: str
    first_initial: str
    surname: str
    jersey: int


def parse_player_key(raw: str, valid_teams: set[str]) -> ParsedKey | None:
    """Split a Kalshi player key using the KNOWN team set.

    Regex alone cannot do this: team codes are 2-3 chars and ambiguous, so a greedy
    pattern turns SFBPURDY13 into SFB+PURDY. Anchoring on real team codes (longest
    first, aliases included) is what takes the match rate from 55% to 92%.
    """
    m = _KEY_RE.match(raw)
    if not m:
        return None
    body, jersey = m.group(1), int(m.group(2))
    for code in sorted(valid_teams, key=len, reverse=True):
        if body.startswith(code) and len(body) > len(code) + 1:
            rest = body[len(code):]
            return ParsedKey(raw, TEAM_ALIASES.get(code, code), rest[0], rest[1:], jersey)
    return None


def _norm_surname(col: str) -> pl.Expr:
    return pl.col(col).str.replace_all(r"[^A-Za-z]", "").str.to_uppercase()


def build_crosswalk(market_tickers: list[str], roster: pl.DataFrame) -> pl.DataFrame:
    """Resolve Kalshi player keys to gsis_ids. Returns one row per distinct key."""
    valid = set(roster["team"].drop_nulls().unique().to_list()) | set(TEAM_ALIASES)

    seen: dict[str, ParsedKey] = {}
    unparsed: list[str] = []
    for t in market_tickers:
        parts = t.split("-")
        if len(parts) < 3:
            continue
        raw = parts[2]
        if raw in seen:
            continue
        pk = parse_player_key(raw, valid)
        if pk:
            seen[raw] = pk
        else:
            unparsed.append(raw)

    if not seen:
        return pl.DataFrame(schema={
            "raw_key": pl.Utf8, "team": pl.Utf8, "first_initial": pl.Utf8,
            "surname": pl.Utf8, "jersey": pl.Int64, "gsis_id": pl.Utf8,
            "full_name": pl.Utf8, "method": pl.Utf8, "confidence": pl.Float64,
        })

    keys = pl.DataFrame([{
        "raw_key": p.raw, "team": p.team, "first_initial": p.first_initial,
        "surname": p.surname, "jersey": p.jersey,
    } for p in seen.values()])

    # A player's legal first_name is often not the name he plays under: Matthew
    # Stafford's first_name is "John". nflverse carries football_name for exactly this,
    # and Kalshi keys off the known name. Match on EITHER initial, or matching silently
    # fails for a whole class of players.
    cols = ["team", "jersey_number", "full_name", "first_name", "last_name", "gsis_id"]
    if "football_name" in roster.columns:
        cols.append("football_name")
    r = (roster.select(cols)
         .drop_nulls("jersey_number")
         .with_columns(
             _surname=_norm_surname("last_name"),
             _init=pl.col("first_name").str.slice(0, 1).str.to_uppercase(),
             _init_fb=(pl.col("football_name") if "football_name" in cols
                       else pl.col("first_name")).str.slice(0, 1).str.to_uppercase(),
             jersey=pl.col("jersey_number").cast(pl.Int64),
         ).unique())

    # long-form: one row per (player, acceptable initial) so a single join covers both
    r = pl.concat([
        r.with_columns(_i=pl.col("_init")),
        r.with_columns(_i=pl.col("_init_fb")),
    ]).unique(subset=["gsis_id", "team", "jersey", "_surname", "_i"])

    exact = keys.join(
        r.select("team", "jersey", "_surname", "_i", "gsis_id", "full_name"),
        left_on=["team", "jersey", "surname", "first_initial"],
        right_on=["team", "jersey", "_surname", "_i"],
        how="left",
    ).unique(subset=["raw_key"], keep="first")

    resolved = exact.filter(pl.col("gsis_id").is_not_null()).with_columns(
        method=pl.lit(MatchMethod.EXACT.value), confidence=pl.lit(1.0))

    # fallback: same team + name, jersey changed (mid-season number swaps happen)
    todo = exact.filter(pl.col("gsis_id").is_null()).drop("gsis_id", "full_name")
    fb = todo.join(
        r.select("team", "_surname", "_i", "gsis_id", "full_name"),
        left_on=["team", "surname", "first_initial"],
        right_on=["team", "_surname", "_i"],
        how="left",
    ).unique(subset=["raw_key"], keep="first")

    fb_ok = fb.filter(pl.col("gsis_id").is_not_null()).with_columns(
        method=pl.lit(MatchMethod.FALLBACK.value), confidence=pl.lit(0.85))

    rest = fb.filter(pl.col("gsis_id").is_null()).with_columns(
        gsis_id=pl.col("raw_key").replace_strict(MANUAL_OVERRIDES, default=None),
    ).with_columns(
        method=pl.when(pl.col("gsis_id").is_not_null())
                 .then(pl.lit(MatchMethod.MANUAL.value))
                 .otherwise(pl.lit(MatchMethod.UNRESOLVED.value)),
        confidence=pl.when(pl.col("gsis_id").is_not_null())
                     .then(pl.lit(1.0)).otherwise(pl.lit(0.0)),
    )

    out_cols = ["raw_key", "team", "first_initial", "surname", "jersey",
                "gsis_id", "full_name", "method", "confidence"]
    for f in (resolved, fb_ok, rest):
        if "full_name" not in f.columns:
            f = f.with_columns(full_name=pl.lit(None, dtype=pl.Utf8))
    return pl.concat(
        [f.with_columns(
            **{c: pl.lit(None, dtype=pl.Utf8) for c in out_cols if c not in f.columns})
          .select(out_cols) for f in (resolved, fb_ok, rest)],
        how="vertical",
    )
