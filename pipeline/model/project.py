"""Projection job: markets -> features -> simulation -> signals in Neon.

Writes a Projection and, where a real market price exists, a Signal. A market with
no quote produces NO signal: an edge computed against an imagined price is the exact
fabrication Section 0 rule 3 forbids.

MODEL VERSIONING MATTERS HERE. Runs are tagged, and the preseason smoke run is tagged
distinctly, because projecting preseason usage from regular-season data is known to be
wrong -- starters play a series or two. Those signals exercise the pipeline end to end
on real prices and real settlements; they must never be mistaken for a validated
model, and the version tag is what keeps them separable.
"""
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone

import duckdb
import pyarrow.parquet as pq

from pipeline.common import config, db, tickers
from pipeline.features.crosswalk import build_crosswalk
from pipeline.backtest.point_in_time import (
    LeakageError,
    assert_features_predate_kickoff,
)
from pipeline.features.availability import build_inactivity_table, status_lookup
from pipeline.features.wind import describe as describe_wind, wind_effect
from pipeline.ingest.weather import forecast_for_game
from pipeline.features.starters import STARTER_DEPTH, resolve_starters
from pipeline.model.features_for_projection import (
    InsufficientHistory,
    load_player_inputs,
)
from pipeline.features.defense import (
    build_pass_defense_grades,
    build_rush_defense_grades,
)
from pipeline.model.adjustments import (
    defense_adjustment,
    rest_adjustment,
    usage_trend_adjustment,
)
from pipeline.features.splits import build_availability, build_with_without
from pipeline.features.usage import build_player_game_usage
from pipeline.model.context import defense_detail, load_context
from pipeline.model.player_volume import project_player_volume
from pipeline.model.team_volume import (
    build_team_volume,
    project_for_game,
    volume_dict,
)
from pipeline.model.anytime_td import (
    build_baselines,
    load_td_inputs,
    project_anytime_td,
)
from pipeline.model.rationale import build_rationale
from pipeline.model.signal import compute_edge
from pipeline.model.simulate import (
    Adjustment,
    VolumeProjection,
    project_passing_tds,
    project_passing_yards,
    project_receiving_yards,
    project_receptions,
    project_rushing_yards,
)

# Which simulator handles each Kalshi market family.
MARKET_MODEL = {
    "rec_yds": "receiving_yards",
    "receptions": "receptions",
    "rush_yds": "rushing_yards",
    "pass_yds": "passing_yards",
    "pass_tds": "passing_tds",
    "anytime_td": "anytime_td",
}


# A 0c ask is not a price you can be filled at -- it is an empty or one-sided book
# reported as a number. 48% of preseason entry prices sat at these extremes.
MIN_TRADEABLE_ASK = 0.01
MAX_TRADEABLE_ASK = 0.99

# When the model and the market disagree by more than this, the model is almost
# always missing something the market knows (a scratch, a role change, weather) --
# it is not 50c of free edge. Flagged rather than silently emitted as a monster edge.
IMPLAUSIBLE_DIVERGENCE = 0.50


# Backtesting and live serving need DIFFERENT prices, and conflating them is why the
# board was empty for its whole life. A settled market's entry price must be pinned to
# a fixed horizon so it cannot borrow information from after that point. An open
# market's price is simply the freshest quote there is. One query cannot serve both:
# the settled path filters on `result in ('yes','no')`, and an open market has no
# result yet -- so a shared query silently restricted the live board to games that
# were already over.


def _settled_prices(archive_glob: str, mins_before_close: int) -> list[dict]:
    """Backtest entry prices: the ask at T-minus-N for markets that have settled.

    Only snapshots at or before the horizon are eligible, so the entry price cannot
    borrow information from after the reconstruction point.
    """
    con = duckdb.connect()
    return con.execute(f"""
        with ranked as (
            select *,
                   row_number() over (
                       partition by market_ticker order by mins_to_close asc
                   ) rn
            from read_parquet('{archive_glob}')
            where mins_to_close >= {int(mins_before_close)}
              and yes_ask is not null
              and yes_ask >= {MIN_TRADEABLE_ASK}
              and yes_ask <= {MAX_TRADEABLE_ASK}
        )
        select market_ticker, series_ticker, market_type, strike, yes_ask, result,
               close_time, mins_to_close, ts as price_ts
        from ranked where rn = 1 and result in ('yes', 'no')
    """).to_arrow_table().to_pylist()


def _open_prices(archive_glob: str, max_price_age_mins: int) -> list[dict]:
    """Live board prices: the most recent quote for a market that has not closed.

    `mins_to_close` is recomputed against the clock rather than read from the
    snapshot, because the archived value was true when the snapshot was taken and is
    stale by exactly the age of that snapshot.
    """
    con = duckdb.connect()
    return con.execute(f"""
        with ranked as (
            select *,
                   row_number() over (
                       partition by market_ticker order by ts desc
                   ) rn
            from read_parquet('{archive_glob}')
            where result is null
              and close_time > now()
              and yes_ask is not null
              and yes_ask >= {MIN_TRADEABLE_ASK}
              and yes_ask <= {MAX_TRADEABLE_ASK}
        )
        select market_ticker, series_ticker, market_type, strike, yes_ask, result,
               close_time,
               cast(date_diff('minute', now(), close_time) as bigint) as mins_to_close,
               ts as price_ts
        from ranked
        where rn = 1
          and date_diff('minute', ts, now()) <= {int(max_price_age_mins)}
    """).to_arrow_table().to_pylist()


def open_market_census(archive_glob: str, max_price_age_mins: int) -> dict:
    """Why the live board is empty, counted rather than guessed.

    An empty board has three very different causes -- no upcoming markets listed,
    markets listed but nobody quoting them, or quotes that have gone stale because the
    archiver stopped. They look identical to a user and demand different responses, so
    the UI is given the counts instead of a blank page.
    """
    con = duckdb.connect()
    listed, quoted = con.execute(f"""
        select
          count(distinct market_ticker) as listed,
          count(distinct case
                  when yes_ask is not null
                   and yes_ask >= {MIN_TRADEABLE_ASK}
                   and yes_ask <= {MAX_TRADEABLE_ASK}
                  then market_ticker end) as quoted
        from read_parquet('{archive_glob}')
        where result is null and close_time > now()
    """).fetchone()
    return {
        "listed": int(listed or 0),
        "quoted": int(quoted or 0),
        "fresh": len(_open_prices(archive_glob, max_price_age_mins)),
        "max_price_age_mins": int(max_price_age_mins),
    }


# Event-ticker parsing lives in pipeline/common/tickers.py. It used to be four separate
# regexes and two team-code tables in THIS file, and every one of the three anchoring
# bugs found in this project came from one copy being fixed while the others were not.
_split_matchup = tickers.split_matchup
_event_date = tickers.event_date
_TEAM_CODES = tickers.TEAM_CODES
PRESEASON_MONTHS = tickers.PRESEASON_MONTHS


def _week_index(schedule_path: str, season: int) -> dict[str, int]:
    """game date -> week, so an injury report can be read as of the right week."""
    try:
        rows = duckdb.connect().execute(f"""
            select distinct cast(gameday as varchar), week
            from read_parquet('{schedule_path}')
            where season = {int(season)} and gameday is not null
        """).fetchall()
    except Exception:
        return {}
    return {d: int(w) for d, w in rows}


def _spread_index(schedule_path: str, season: int) -> dict[tuple[str, str], float]:
    """(game date, team) -> that TEAM's spread. Positive means the team is favoured.

    nflverse `spread_line` is positive when the HOME team is favoured, so the away
    team's spread is its negation. Verified against outcomes rather than assumed:
    over 1,084 team-games, six-point favourites pass on 53.7% of snaps and six-point
    underdogs on 59.5%, and the correlation between this signed spread and pass rate
    is -0.200 -- matching the -0.188 team_volume.py measured when it fitted the slope.
    Getting the sign backwards would push every projection exactly the wrong way.
    """
    try:
        rows = duckdb.connect().execute(f"""
            select cast(gameday as varchar), home_team, away_team, spread_line
            from read_parquet('{schedule_path}')
            where season = {int(season)} and spread_line is not null
              and gameday is not null
        """).fetchall()
    except Exception:
        return {}
    out: dict[tuple[str, str], float] = {}
    for day, home, away, sp in rows:
        out[(day, home)] = float(sp)
        out[(day, away)] = -float(sp)
    return out


def _assert_pbp_predates_slate(current_pbp_path: str, markets: list, venue_of: dict) -> None:
    """Refuse to run if the current-season play-by-play contains a game being projected.

    Blends current-season team volume into the projection, so if that file already
    holds the game we are pricing, the model is reading the answer. A leaky model looks
    like a brilliant one, which is exactly why this fails the run rather than warning.
    """
    from datetime import datetime as _dt, timezone as _tz

    kickoffs = [
        venue_of[k][2] for k in venue_of if venue_of.get(k) and venue_of[k][2] is not None
    ]
    if not kickoffs:
        return
    earliest = min(kickoffs)
    try:
        last_played = duckdb.connect().execute(f"""
            select max(cast(game_date as varchar)) from read_parquet('{current_pbp_path}')
        """).fetchone()[0]
    except Exception:
        return              # no such column or no file: nothing to assert against
    if not last_played:
        return
    try:
        last_dt = _dt.fromisoformat(str(last_played)[:10]).replace(tzinfo=_tz.utc)
    except ValueError:
        return
    if last_dt >= earliest.replace(hour=0, minute=0, second=0, microsecond=0):
        raise LeakageError(
            f"current-season play-by-play runs to {last_played}, at or after the "
            f"earliest kickoff being projected ({earliest.date()}). The projection "
            f"would be built from the game it is predicting."
        )


def _apply_wind(tv, wx):
    """Shift the pass/run split for wind, leaving total plays alone.

    Same contract as the spread: wind changes what a team CHOOSES to do, not how many
    snaps it gets. The measured play-count effect is r=-0.024, indistinguishable from
    noise, so inventing one here would be fabricating signal.
    """
    if wx is None or wx.pass_rate_delta == 0.0:
        return tv
    from pipeline.model.team_volume import TeamVolume
    rate = max(0.30, min(0.80, tv.pass_rate + wx.pass_rate_delta))
    return TeamVolume(
        team=tv.team, plays=tv.plays,
        pass_attempts=tv.plays * rate, rush_attempts=tv.plays * (1 - rate),
        pass_rate=rate, games_current=tv.games_current, prior_only=tv.prior_only,
    )


def _venue_index(schedule_path: str, season: int) -> dict[str, tuple]:
    """game date -> (stadium_id, roof, kickoff UTC). One entry per date+home team.

    Keyed by (date, home_team) because two games can share a date. A blank roof --
    which nflverse leaves for some retractable venues before kickoff -- is treated as
    NOT outdoor: guessing "open" would apply a wind adjustment to an indoor game.
    """
    from datetime import datetime as _dt, timezone as _tz
    try:
        rows = duckdb.connect().execute(f"""
            select cast(gameday as varchar), home_team, away_team,
                   stadium_id, roof, cast(gametime as varchar)
            from read_parquet('{schedule_path}')
            where season = {int(season)} and gameday is not null
        """).fetchall()
    except Exception:
        return {}
    out: dict[str, tuple] = {}
    for day, home, away, sid, roof, gametime in rows:
        try:
            ko = _dt.fromisoformat(f"{day}T{gametime or '17:00'}:00").replace(tzinfo=_tz.utc)
        except ValueError:
            ko = None
        for team in (home, away):
            out[f"{day}|{team}"] = (sid, roof, ko)
    return out


def _rest_context(schedule_path: str, season: int) -> dict:
    """(team, date) -> (days_rest, is_short_week, is_post_bye).

    rest_adjustment existed, was documented and tested, and had never been called.
    """
    from pipeline.features.rest import build

    tbl = pq.read_table(schedule_path)
    r = build(tbl, season=season)
    out = {}
    for row in r.to_pylist():
        out[(row["team"], str(row["game_date"]))] = (
            row["days_rest"], bool(row["is_short_week"]), bool(row["is_post_bye"]),
        )
    return out


_opponent_of = tickers.opponent_of
_game_label = tickers.game_label
_is_preseason = tickers.is_preseason


def run(
    archive_glob: str,
    pbp_path: str,
    roster_path: str,
    players_path: str | None = None,
    depth_path: str | None = None,
    injuries_path: str | None = None,
    snaps_path: str | None = None,
    schedule_path: str | None = None,
    season: int = 2026,
    model_version: str = "nfl-v1",
    mins_before_close: int = 60,
    iterations: int = 20_000,
    seed: int = 20260909,
    allow_preseason: bool = False,
    allow_backups: bool = False,
    mode: str = "live",
    max_price_age_mins: int = 180,
    refresh: bool = False,
    current_pbp_path: str | None = None,
    current_snaps_path: str | None = None,
) -> dict:
    if mode not in ("live", "settled"):
        raise ValueError(f"mode must be 'live' or 'settled', got {mode!r}")

    if mode == "settled":
        markets = _settled_prices(archive_glob, mins_before_close)
        census = None
    else:
        if refresh:
            # Take a snapshot before pricing rather than hoping one is lying around.
            # CI checks out a bare repo -- the archive directory is EMPTY there, so a
            # live run that only reads the archive finds nothing and reports an empty
            # board that looks exactly like an unquoted market. This also means the
            # board is priced off a quote seconds old instead of hours.
            from pipeline.ingest.kalshi_archiver import snapshot
            # Recorded as an archiver run because that is what it is -- it writes the
            # same parquet to the same archive and the same blob. Without the record
            # the staleness banner reports the last standalone archiver run and calls
            # the data old while this job is refreshing it every hour.
            with db.track("kalshi_archiver") as snap_run:
                snap = snapshot(sports=("nfl",), with_orderbook=False, adaptive=False)
                snap_run["rows"] = snap.get("rows", 0)
                snap_run["meta"] = {"quoted": snap.get("quoted", 0),
                                    "via": "project --refresh",
                                    "blob": bool(snap.get("blob_url")),
                                    "errors": len(snap.get("errors") or [])}
            print(f"refreshed: rows={snap.get('rows', 0)} "
                  f"quoted={snap.get('quoted', 0)} path={snap.get('path')}")
        markets = _open_prices(archive_glob, max_price_age_mins)
        census = open_market_census(archive_glob, max_price_age_mins)

    if not markets:
        return {"markets": 0, "projections": 0, "signals": 0, "skipped": {},
                "mode": mode, "census": census,
                "with_adjustments": 0, "share_based_baselines": 0,
                "with_p_inactive": 0, "with_spread": 0,
                "outdoor_games": 0, "with_wind": 0,
                "teams_with_current_season": 0}

    roster = pq.read_table(roster_path)

    # Starters and absences are resolved PER WEEK, not once per run.
    #
    # An injury report accumulates. Resolved once with no week filter, every player
    # ever listed Out stays out for the rest of the season: 726 distinct players in
    # 2025 against 48 in week 1 and 108 in week 18. By late season that benches 186
    # skill players and promotes their backups in their place -- and the projection
    # skips non-starters silently, so nothing would have surfaced it.
    week_of = _week_index(schedule_path, season) if schedule_path else {}
    spread_of = _spread_index(schedule_path, season) if schedule_path else {}
    venue_of = _venue_index(schedule_path, season) if schedule_path else {}

    # Wind is the largest single game-context effect measured here: above 20mph pass
    # rate drops 6.7 points against 2.2 for a full game-script swing, and it hits
    # efficiency as well as volume. nflverse only backfills weather AFTER kickoff, so
    # the forecast comes from Open-Meteo. A failed fetch yields None and no
    # adjustment -- never a silent zero, which would be indistinguishable from calm.
    _wx: dict[str, object] = {}

    def wind_for(date_key: str | None):
        if not date_key or date_key not in venue_of:
            return None
        sid, roof, ko = venue_of[date_key]
        # Memoised on the VENUE, not on date|team: both teams in a game share a
        # stadium, so keying by team would fetch every forecast twice.
        cache_key = f"{sid}|{ko}"
        if cache_key not in _wx:
            try:
                f = forecast_for_game(sid, roof, ko)
            except Exception:
                f = None
            _wx[cache_key] = wind_effect(f.wind_mph, f.lead_hours) if f else None
        return _wx[cache_key]

    _starters: dict[int | None, dict] = {}
    _absent: dict[int | None, list[str]] = {}

    def starters_for(wk: int | None) -> dict:
        if wk not in _starters:
            _starters[wk] = (
                resolve_starters(depth_path, injuries_path, week=wk, season=season)
                if depth_path else {}
            )
        return _starters[wk]

    # P(no offensive snap), measured rather than assumed. VolumeProjection has carried
    # a p_inactive field since the simulator was written and it has never been set, so
    # every prop has been priced as though the player is certain to play -- no left
    # tail at all, on the single largest risk a yardage line carries.
    inactivity = None
    # CURRENT-season snaps, not the prior season's. The two consumers of snap counts
    # want different files: the with/without splits are built from history, while
    # P(inactive) must be measured on the season being projected. Pairing a 2026
    # injury report with 2025 snaps makes every cell resolve to 1.000 -- see the guard
    # in features/availability.py -- so this is now explicit rather than inherited.
    _inactivity_snaps = current_snaps_path or snaps_path
    if injuries_path and _inactivity_snaps and players_path:
        try:
            inactivity = build_inactivity_table(
                injuries_path, _inactivity_snaps, players_path, season)
        except Exception:
            inactivity = None

    _status: dict[int | None, dict] = {}

    def status_for(wk: int | None) -> dict:
        if wk not in _status:
            _status[wk] = (
                status_lookup(injuries_path, season, wk)
                if injuries_path and wk is not None else {}
            )
        return _status[wk]

    def absent_for(wk: int | None) -> list[str]:
        """Teammates ruled out this week, so a with/without split can move a share."""
        if wk not in _absent:
            if depth_path and injuries_path:
                from pipeline.features.starters import injured_out
                _absent[wk] = sorted(injured_out(injuries_path, week=wk, season=season))
            else:
                _absent[wk] = []
        return _absent[wk]

    # Share x team volume replaces the raw historical count as the volume baseline.
    # A raw count assumes both team volume and the player's role stay put; splitting
    # them lets the projection respond when either moves.
    team_vol = usage_tbl = splits_tbl = None
    try:
        # The current-season blend was inert: build_team_volume was called with one
        # argument, so `current_pbp_path` was None, the blend weight was 0, and
        # FULL_WEIGHT_GAMES never engaged. Team volume was 100% prior-season shrunk to
        # the league mean -- which, given PLAYS_SHRINKAGE = 0.14, meant plays per game
        # was effectively the league constant for every team, forever.
        # The most damaging leak available here: building a "prediction" for a game
        # from play-by-play that already contains it. This module existed, was tested,
        # and was called by nothing -- a guard that never runs is not a guard.
        if current_pbp_path:
            _assert_pbp_predates_slate(current_pbp_path, markets, venue_of)
        team_vol = volume_dict(build_team_volume(pbp_path, current_pbp_path))
        blend_teams = sum(1 for v in team_vol.values() if not v.prior_only)
        usage_tbl = build_player_game_usage(pbp_path)
        if players_path and snaps_path:
            splits_tbl = build_with_without(
                usage_tbl, build_availability(snaps_path, players_path),
                pq.read_table(players_path), "target_share")
    except Exception:
        team_vol = usage_tbl = splits_tbl = None

    rest_ctx = {}
    if schedule_path:
        try:
            rest_ctx = _rest_context(schedule_path, season)
        except Exception:
            rest_ctx = {}

    td_baselines = build_baselines(pbp_path, players_path) if players_path else {}
    # graded once and reused: the rationale needs the SPECIFIC split this prop runs
    # into, not the team-level average the multiplier uses
    grades = None
    if players_path:
        try:
            grades = (build_pass_defense_grades(pbp_path, players_path),
                      build_rush_defense_grades(pbp_path))
        except Exception:
            grades = None
    xw = build_crosswalk([m["market_ticker"] for m in markets], roster)
    # UNRESOLVED keys carry gsis_id = None and are excluded here. FALLBACK matches
    # (jersey ignored) resolve but are less certain -- a shared surname and initial
    # on one roster would produce the wrong player -- so the confidence travels with
    # the row and is stated in the rationale rather than silently equated to EXACT.
    by_key = {
        r["raw_key"]: r for r in xw.to_pylist() if r["gsis_id"] is not None
    }

    import psycopg

    now = datetime.now(timezone.utc)
    skipped: dict[str, int] = {}
    n_proj = n_sig = 0
    # Adjustment coverage is reported, because an adjustment that silently stops
    # firing looks identical to one that is working. This job once explained an
    # opponent matchup in every rationale while applying it to none of them: the
    # condition read an unused parameter that was always None.
    n_with_adj = 0
    # How many baselines came from share x team volume rather than a raw count.
    # Reported for the same reason as with_adjustments: a modelling layer that stops
    # being reached looks identical to one that is working.
    n_share_based = 0
    # How many projections carry a non-zero DNP mass. Reported for the same reason as
    # with_adjustments: a layer that stops being reached looks identical to one that
    # is working. p_inactive in particular was dead from the day it was written.
    n_p_inactive = 0
    #: Projections whose team volume was adjusted for game script.
    n_spread = 0
    #: Wind is rare by nature, so the guard reports outdoor games SEEN alongside
    #: adjustments APPLIED. Without both, a broken Open-Meteo fetch is
    #: indistinguishable from a calm week.
    n_outdoor = 0
    n_wind = 0
    #: Share of teams whose volume carries any current-season data. Zero before week 1
    #: is correct; zero in November means the blend is inert again.
    blend_teams = 0

    def skip(reason: str):
        skipped[reason] = skipped.get(reason, 0) + 1

    with psycopg.connect(config.DATABASE_URL) as conn:
        # A settled market's entry price never changes, so re-running the backtest
        # would emit the same signal again every day and the Track Record would count
        # one decision as thirty. Live prices DO change, so live mode re-emits by
        # design -- the board wants the newest quote.
        already: set[str] = set()
        if mode == "settled":
            with conn.cursor() as cur:
                cur.execute(
                    'select distinct "marketTicker" from "Signal" '
                    'where "modelVersion" = %s',
                    (model_version,),
                )
                already = {r[0] for r in cur.fetchall()}

        for m in markets:
            # Both selectors return the snapshot this price came from. It is the
            # information boundary for the decision and the age the board renders.
            price_as_of = m.get("price_ts") or now
            if m["market_ticker"] in already:
                skip("already_emitted"); continue
            parts = m["market_ticker"].split("-")
            if len(parts) < 3:
                skip("unparseable_ticker"); continue
            if not allow_preseason and _is_preseason(m["market_ticker"]):
                skip("preseason_refused"); continue
            xr = by_key.get(parts[2])
            if not xr:
                skip("unresolved_player"); continue
            if xr.get("method") == "FALLBACK":
                skip("matched_by_fallback")   # counted, not refused

            model = MARKET_MODEL.get(m["market_type"])
            if not model:
                skip("unmodelled_market"); continue

            # The volume driver this market settles on. Assigned HERE, before
            # load_context reads it. It used to be assigned ~120 lines further down,
            # after its own first use: the first market of every run therefore raised
            # UnboundLocalError into a bare `except` and silently lost all context
            # including the usage-trend adjustment, and every market after it inherited
            # the PREVIOUS market's driver -- so a rushing prop following a receiving
            # prop had its "carries trend" computed from targets.
            volume_metric = {
                "receiving_yards": "targets", "receptions": "targets",
                "anytime_td": "scoring-zone touches",
                "rushing_yards": "carries",
                "passing_yards": "pass attempts", "passing_tds": "pass attempts",
            }[model]

            # This market's own week, so the injury report is read as of the game
            # being projected rather than cumulatively across the season.
            game_date = _event_date(m["market_ticker"])
            game_week = week_of.get(game_date)
            depth = starters_for(game_week)
            absent_ids = absent_for(game_week)
            # A Questionable player has roughly a 40% chance of taking no offensive
            # snap; the starter filter only refuses Out/Doubtful, so without this he
            # is projected as a certainty.
            p_inactive = 0.0
            if inactivity is not None and not inactivity.is_empty:
                p_inactive = inactivity.for_player(
                    status_for(game_week).get(xr["gsis_id"]))

            # A backup's baseline describes a role he no longer holds. Refuse rather
            # than project it: the market knows he is behind someone, our usage
            # history does not.
            if depth and not allow_backups:
                st = depth.get(xr["gsis_id"])
                if st is None:
                    skip("not_starting"); continue

            try:
                pi = load_player_inputs(pbp_path, xr["gsis_id"])
            except InsufficientHistory:
                skip("insufficient_history"); continue

            strike = m["strike"]
            if strike is None:
                skip("no_strike"); continue

            team_code = (xr.get("team") or "")
            opponent = _opponent_of(m["market_ticker"], team_code)
            # Positive means this team is favoured. Both project_for_game call sites
            # passed None until now, so SPREAD_PASS_RATE_SLOPE was dead and every
            # pass/run split was the season average whether the team was a ten-point
            # favourite or a ten-point dog -- while the comment below claimed
            # otherwise.
            team_spread = spread_of.get((game_date, team_code)) if game_date else None
            # The price we are modelling against must predate kickoff. In live mode
            # the close-time filter makes this near-impossible; in settled mode it is
            # the whole integrity question, because a snapshot taken after kickoff
            # would be pricing a game whose result is already known.
            venue = venue_of.get(f"{game_date}|{team_code}") if game_date else None
            if venue and venue[2] is not None:
                try:
                    assert_features_predate_kickoff(price_as_of, venue[2])
                except LeakageError:
                    skip("leakage_price_after_kickoff"); continue

            wx = wind_for(f"{game_date}|{team_code}") if game_date else None
            wind_note = describe_wind(wx) if wx else ""
            # Applied to volume via the pass rate and to efficiency via the simulator.
            # Rushing is left alone: the measured effect is on the passing game.
            eff_mult = wx.efficiency_multiplier if wx else 1.0

            # Context is loaded BEFORE the adjustments now: recent form is a model
            # input, not just an explanation. It was previously computed only for the
            # rationale, so the panel described a trend the projection never applied.
            pctx = None
            try:
                pctx = load_context(pbp_path, xr["gsis_id"], team_code,
                                    m["market_type"], volume_metric, float(strike))
                if grades and opponent:
                    d, rk, split = defense_detail(grades[0], grades[1], opponent,
                                                  m["market_type"], xr.get("position"))
                    pctx.def_metric, pctx.def_rank, pctx.def_split = d, rk, split
            except Exception as e:
                # Counted, not swallowed. A bare `except` here is what concealed the
                # volume_metric bug above for as long as it existed.
                pctx = None
                skip(f"context_failed:{type(e).__name__}")

            # Baseline: share x team volume where we can, raw count otherwise.
            share_metric = {"receiving_yards": "target_share",
                            "receptions": "target_share",
                            "rushing_yards": "carry_share"}.get(model)
            share_note = None
            baseline_override = None

            # A starting quarterback IS his team's passing volume, so his attempts
            # come from the team projection directly. That also connects passing
            # props to game script: an underdog throws more.
            if model in ("passing_yards", "passing_tds") and team_vol \
                    and team_code in team_vol:
                tvq = _apply_wind(project_for_game(team_vol[team_code], team_spread), wx)
                # keep his own share of dropbacks rather than assuming he takes all
                own = (pi.attempts_per_game / tvq.pass_attempts
                       if tvq.pass_attempts else 0)
                if 0.5 <= own <= 1.15:
                    baseline_override = tvq.pass_attempts * own
                    share_note = type("SN", (), {
                        "market_share": own, "team_volume": tvq.pass_attempts,
                        "projected": baseline_override, "split_delta": None,
                        "split_teammate": None, "notes": None})()

            if share_metric and team_vol and usage_tbl is not None and team_code in team_vol:
                tv = _apply_wind(project_for_game(team_vol[team_code], team_spread), wx)
                team_units = (tv.pass_attempts if share_metric == "target_share"
                              else tv.rush_attempts)
                raw_pg = (pi.targets_per_game if share_metric == "target_share"
                          else pi.carries_per_game)
                pvol = project_player_volume(
                    usage_tbl, splits_tbl, xr["gsis_id"], team_units,
                    absent_teammates=absent_ids, metric=share_metric,
                    fallback_per_game=raw_pg)
                if pvol and pvol.projected > 0:
                    baseline_override = pvol.projected
                    share_note = pvol

            adj: list[Adjustment] = []
            if grades is not None and opponent:
                # The player's own position, so the multiplier uses the same split
                # the Why panel quotes. Without it the panel said "allows +0.081 EPA
                # to TEs" while the number that moved was the team-wide average --
                # and for a TE facing SEA those differ by 6.7 points, in opposite
                # directions.
                a = defense_adjustment(opponent, m["market_type"],
                                       grades[0], grades[1],
                                       position=xr.get("position"))
                if a:
                    adj.append(a)
            if pctx is not None:
                a = usage_trend_adjustment(pctx.recent_mean, pctx.season_mean,
                                           pctx.recent_games)
                if a:
                    adj.append(a)
            rc = rest_ctx.get((team_code, _event_date(m["market_ticker"])))
            if rc:
                a = rest_adjustment(rc[0], rc[1], rc[2])
                if a:
                    adj.append(a)

            if model == "receiving_yards":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      baseline_override or pi.targets_per_game, adj,
                                      dispersion=pi.target_dispersion,
                                      p_inactive=p_inactive)
                out = project_receiving_yards(vp, pi.catch_rate, pi.yards_per_catch,
                                              [strike], efficiency_multiplier=eff_mult, iterations=iterations, seed=seed)
            elif model == "receptions":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      baseline_override or pi.targets_per_game, adj,
                                      dispersion=pi.target_dispersion,
                                      p_inactive=p_inactive)
                out = project_receptions(vp, pi.catch_rate, [strike],
                                         iterations=iterations, seed=seed)
            elif model == "rushing_yards":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      baseline_override or pi.carries_per_game, adj,
                                      dispersion=pi.carry_dispersion,
                                      p_inactive=p_inactive)
                out = project_rushing_yards(vp, pi.yards_per_carry, [strike],
                                            iterations=iterations, seed=seed)
            elif model == "anytime_td":
                # A different problem from a total: driven by WHERE the touches come,
                # not how many. A goal-line carry scores 3.3x more often than a
                # red-zone target outside the five, and a quarter of all touchdowns
                # are scored outside the 20 entirely.
                ti = load_td_inputs(pbp_path, players_path, xr["gsis_id"], td_baselines)
                mult = 1.0
                for adj_i in adj:
                    mult *= adj_i.multiplier
                td = project_anytime_td(ti, mult, iterations=iterations, seed=seed)
                zone_label = {"gl": "inside the 5", "rz": "6 to 20 yards out",
                              "open": "outside the 20"}
                out = {
                    "mean": td["p_td"], "stdev": 0.0,
                    "percentiles": {}, "p_over_by_strike": {str(strike): td["p_td"]},
                    # One row per scoring zone, so the panel shows WHERE the
                    # probability comes from rather than a single pooled rate.
                    "explain": [
                        {"step": f"touches {zone_label[z]} / game",
                         "value": round(d["touches"], 2),
                         "multiplier": 1.0,
                         # The rate is SHRUNK toward the positional baseline, not
                         # switched to it, so the wording says which it mostly is
                         # rather than claiming it is purely one or the other.
                         "detail": (
                             f"scores {d['rate']:.1%} of the time from there"
                             + (
                                 f" (mostly his own rate, {d['zone_touches']} touches)"
                                 if d.get("own_weight", 0) >= 0.5
                                 else f" (mostly the {ti.position or 'positional'} "
                                      f"baseline — only {d['zone_touches']} of his own "
                                      f"touches there)"
                             )
                         )}
                        for z, d in td.get("by_zone", {}).items() if d["touches"] > 0
                    ],
                }
            elif model == "passing_yards":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.attempts_per_game, adj,
                                      dispersion=pi.attempt_dispersion,
                                      p_inactive=p_inactive)
                out = project_passing_yards(vp, pi.completion_rate,
                                            pi.yards_per_completion, [strike], efficiency_multiplier=eff_mult,
                                            iterations=iterations, seed=seed)
            else:
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.attempts_per_game, adj,
                                      dispersion=pi.attempt_dispersion,
                                      p_inactive=p_inactive)
                out = project_passing_tds(vp, pi.pass_td_rate, [strike],
                                          iterations=iterations, seed=seed)

            p_over = out["p_over_by_strike"][str(strike)]
            if adj:
                n_with_adj += 1
            if baseline_override is not None:
                n_share_based += 1
            proj_id = str(uuid.uuid4())
            baseline_vol = vp.baseline
            edge_preview = compute_edge(p_over, m["yes_ask"])

            divergence = abs(p_over - float(m["yes_ask"]))
            implausible = divergence > IMPLAUSIBLE_DIVERGENCE
            if implausible:
                skip("implausible_divergence_flagged")

            promoted_for = depth.get(xr["gsis_id"]).promoted_for if depth else None
            game_label = _game_label(m["market_ticker"])

            reason = {
                "explain": out["explain"],
                "percentiles": out["percentiles"],
                "mean": out["mean"],
                "p_over": round(p_over, 4),
                "divergence": round(divergence, 4),
                "implausible": implausible,
                "model_version": model_version,
                # Generated HERE, not at read time, so the rendered argument is what
                # the model believed when the signal fired.
                "rationale": build_rationale(
                    player_name=xr.get("full_name") or "This player",
                    market_label=m["market_type"],
                    strike=float(strike),
                    side=edge_preview.side,
                    volume_metric=volume_metric,
                    baseline=float(baseline_vol),
                    games=int(pi.games),
                    adjustments=[a for a in out["explain"] if "multiplier" in a],
                    percentiles=out["percentiles"],
                    mean_outcome=float(out["mean"]),
                    p_over=float(p_over),
                    model_prob=float(edge_preview.model_prob),
                    market_prob=float(edge_preview.market_prob),
                    fee_cents=float(edge_preview.fee_cents),
                    net_edge_cents=float(edge_preview.net_edge_cents),
                    sample_n=int(edge_preview.sample_n),
                    tier=edge_preview.tier.value,
                    opponent=opponent,
                    position=xr.get("position"),
                    ctx=pctx,
                    promoted_for=promoted_for,
                    share_note=(
                        {"share": round(share_note.market_share, 4),
                         "team_units": round(share_note.team_volume, 1),
                         "split_delta": share_note.split_delta,
                         "split_teammate": share_note.split_teammate,
                         "note": share_note.notes}
                        if share_note is not None else None
                    ),
                    match_method=xr.get("method"),
                    game_label=game_label,
                    is_preseason=_is_preseason(m["market_ticker"]),
                ),
            }

            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into "Projection"
                      (id, "playerId", "gameId", "marketType", "modelVersion", "runTs",
                       mean, stdev, distribution, "pOverByStrike", "featureAsOf",
                       source, "ingestedAt")
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)
                    """,
                    # The EVENT ticker (26SEP10SFLAR), not the market ticker. Market
                    # tickers are unique per strike, so storing one as gameId makes
                    # every leg look like it is in a different game and silently
                    # disables all same-game correlation downstream.
                    (proj_id, f"nfl:{xr['gsis_id']}", parts[1],
                     m["market_type"], model_version, now,
                     out["mean"], out["stdev"],
                     json.dumps(out["percentiles"]),
                     json.dumps(out["p_over_by_strike"]),
                     # The price timestamp, NOT the market close. featureAsOf is the
                     # point-in-time guard -- no feature may postdate it -- and
                     # close_time is in the FUTURE for an open market, which made the
                     # guard permit everything up to kickoff. The snapshot we priced
                     # off is the real information boundary.
                     price_as_of, "model", now),
                )
                n_proj += 1
                if p_inactive > 0:
                    n_p_inactive += 1
                if team_spread is not None:
                    n_spread += 1
                if game_date and venue_of.get(f"{game_date}|{team_code}"):
                    from pipeline.ingest.weather import is_outdoor as _is_out
                    if _is_out(venue_of[f"{game_date}|{team_code}"][1]):
                        n_outdoor += 1
                if wx is not None and wx.is_material:
                    n_wind += 1

                edge = edge_preview
                cur.execute(
                    """
                    insert into "Signal"
                      (id, "projectionId", "marketTicker", "runTs", side, "modelProb",
                       "marketProb", "feeCents", "edgeCentsNet", "kellyFraction",
                       tier, "sampleN", reason, "modelVersion", "featureAsOf",
                       "closeTime", "priceAsOf", source, "ingestedAt")
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::"Tier",%s,%s::jsonb,%s,%s,%s,%s,%s,%s)
                    """,
                    (str(uuid.uuid4()), proj_id, m["market_ticker"], now,
                     edge.side,
                     edge.model_prob, edge.market_prob, edge.fee_cents,
                     edge.net_edge_cents, edge.kelly_fraction, edge.tier.value,
                     edge.sample_n, json.dumps(reason), model_version,
                     price_as_of,
                     # Stored so the board can drop a market the moment it closes.
                     # Without it the only ordering available is "most recent run",
                     # which happily serves a game that finished last month.
                     m["close_time"], price_as_of, "model", now),
                )
                n_sig += 1

    return {"markets": len(markets), "projections": n_proj,
            "signals": n_sig, "skipped": skipped,
            "mode": mode, "census": census,
            "with_adjustments": n_with_adj,
            "share_based_baselines": n_share_based,
            "with_p_inactive": n_p_inactive,
            "with_spread": n_spread,
            "outdoor_games": n_outdoor, "with_wind": n_wind,
            "teams_with_current_season": blend_teams}


def main():
    ap = argparse.ArgumentParser(description="Run projections and emit signals")
    ap.add_argument("--archive", default="data/archive/market_snapshots/**/*.parquet")
    ap.add_argument("--pbp", default="data/raw/nflverse/pbp_2025.parquet",
                    help="prior season: the usage and efficiency history")
    ap.add_argument("--current-pbp", default="data/raw/nflverse/pbp_2026.parquet",
                    help="current season, blended into team volume as it accumulates. "
                         "Absent before week 1, which is why the blend must degrade "
                         "rather than fail.")
    ap.add_argument("--roster", default="data/raw/nflverse/rosters_weekly_2026.parquet")
    ap.add_argument("--players", default="data/raw/nflverse/players.parquet")
    ap.add_argument("--depth", default="data/raw/nflverse/depth_charts_2026.parquet")
    ap.add_argument("--injuries", default="data/raw/nflverse/injuries_2026.parquet")
    ap.add_argument("--schedule", default="data/raw/nflverse/schedules.parquet")
    ap.add_argument("--snaps", default="data/raw/nflverse/snap_counts_2025.parquet",
                    help="PRIOR season: the history the with/without splits are built from")
    ap.add_argument("--current-snaps",
                    default="data/raw/nflverse/snap_counts_2026.parquet",
                    help="CURRENT season: what P(inactive) is measured against. A "
                         "prior-season file here silently makes every injured player "
                         "look certain to sit.")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--allow-backups", action="store_true",
                    help="off by default: a backup's prior usage describes a role he "
                         "no longer holds")
    ap.add_argument("--model-version", default="nfl-v1")
    ap.add_argument("--allow-preseason", action="store_true",
                    help="off by default: preseason usage does not predict anything")
    ap.add_argument("--mins-before-close", type=int, default=60,
                    help="settled mode only: the entry-price horizon")
    ap.add_argument("--mode", choices=("live", "settled"), default="live",
                    help="live: price open markets off the freshest quote, for the "
                         "board. settled: reconstruct an entry price at a fixed "
                         "horizon on markets that already resolved, for CLV.")
    ap.add_argument("--max-price-age", type=int, default=180,
                    help="live mode only: refuse a quote older than this many "
                         "minutes rather than present a stale price as current")
    ap.add_argument("--refresh", action="store_true",
                    help="live mode: snapshot Kalshi before pricing. Required in CI, "
                         "where the archive directory starts empty.")
    a = ap.parse_args()

    with db.track("projection") as run_state:
        r = run(
            archive_glob=a.archive,
            pbp_path=a.pbp,
            roster_path=a.roster,
            players_path=a.players,
            depth_path=a.depth,
            injuries_path=a.injuries if Path(a.injuries).exists() else None,
            schedule_path=a.schedule if Path(a.schedule).exists() else None,
            snaps_path=a.snaps if Path(a.snaps).exists() else None,
            season=a.season,
            model_version=a.model_version,
            mins_before_close=a.mins_before_close,
            allow_preseason=a.allow_preseason,
            allow_backups=a.allow_backups,
            current_pbp_path=(a.current_pbp if Path(a.current_pbp).exists() else None),
            current_snaps_path=(a.current_snaps if Path(a.current_snaps).exists() else None),
            mode=a.mode,
            max_price_age_mins=a.max_price_age,
            refresh=a.refresh,
        )
        run_state["rows"] = r["signals"]
        # The census travels with the run so the UI can explain an empty board from
        # the record instead of guessing. Section 12: never serve silence.
        run_state["meta"] = {"skipped": r["skipped"], "markets": r["markets"],
                             "mode": r.get("mode"), "census": r.get("census")}
    adj_n = r.get("with_adjustments", 0)
    print(f"mode={r.get('mode')} markets={r['markets']} "
          f"projections={r['projections']} signals={r['signals']} "
          f"with_adjustments={adj_n} share_based={r.get('share_based_baselines', 0)} "
          f"with_p_inactive={r.get('with_p_inactive', 0)} "
          f"with_spread={r.get('with_spread', 0)} "
          f"outdoor={r.get('outdoor_games', 0)} with_wind={r.get('with_wind', 0)} "
          f"teams_current={r.get('teams_with_current_season', 0)}/32")
    census = r.get("census")
    if census:
        print(f"open markets: listed={census['listed']} quoted={census['quoted']} "
              f"fresh={census['fresh']} (max age {census['max_price_age_mins']}m)")
        if census["listed"] and not census["quoted"]:
            print("  NOTE: upcoming markets are listed but nobody is quoting them "
                  "yet. There is no price to have an edge against; this is the "
                  "market's state, not a pipeline failure.")
        elif census["quoted"] and not census["fresh"]:
            print("  WARNING: every quote is older than the freshness limit. The "
                  "archiver has probably stopped -- check the archive-markets job.")
    if r["signals"] and r.get("with_p_inactive", 0) == 0:
        print("  WARNING: no projection carries a DNP probability. Either no injury "
              "report is published yet, or the availability table failed to build -- "
              "the two look identical from here, so check that injuries and snap "
              "counts are both present.")
    if r["signals"] and adj_n == 0:
        print("  WARNING: no signal carries an adjustment. The matchup layer is "
              "inert -- check that grades loaded and opponents resolved.")
    if r["skipped"]:
        print("skipped:")
        for k, v in sorted(r["skipped"].items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
