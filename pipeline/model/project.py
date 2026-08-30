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

from pipeline.common import config, db
from pipeline.features.crosswalk import build_crosswalk
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
from pipeline.model.context import defense_detail, load_context
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


def _entry_prices(archive_glob: str, mins_before_close: int) -> list[dict]:
    """One row per market: the ask at T-minus-N and the settled result.

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
               close_time, mins_to_close
        from ranked where rn = 1 and result in ('yes', 'no')
    """).to_arrow_table().to_pylist()


# Preseason snap distribution bears no relation to the regular season -- starters
# play a series or two. Projecting it produces confident nonsense, so it is refused
# outright rather than left to a caller to remember.
PRESEASON_MONTHS = ("AUG", "JUL")


# Kalshi's own team codes, used to split an event ticker. A midpoint split is wrong
# whenever the two codes are different lengths: ARILV becomes AR/ILV rather than
# ARI/LV. Same failure as splitting SFBPURDY13 into SFB+PURDY.
_TEAM_CODES = {
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU",
    "IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT",
    "SEA","SF","TB","TEN","WAS","JAC","LA","WSH",
}


def _split_matchup(teams: str) -> tuple[str, str] | None:
    """Split a concatenated matchup by anchoring on real team codes, longest first."""
    for away in sorted(_TEAM_CODES, key=len, reverse=True):
        if teams.startswith(away):
            home = teams[len(away):]
            if home in _TEAM_CODES:
                return away, home
    return None


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"])}


def _event_date(market_ticker: str) -> str | None:
    """26SEP10SFLAR -> "2026-09-10", the key rest context is stored under."""
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return None
    m = re.match(r"^(\d{2})([A-Z]{3})(\d{2})[A-Z]{4,8}$", parts[1])
    if not m:
        return None
    yy, mon, dd = m.groups()
    if mon not in _MONTHS:
        return None
    return f"20{yy}-{_MONTHS[mon]:02d}-{int(dd):02d}"


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


def _opponent_of(market_ticker: str, team_code: str) -> str | None:
    """The other team in the event ticker.

    Must be ANCHORED, not subtracted. The previous version did
    `matchup.replace(team_code, "")`, which breaks whenever one code contains
    another: the crosswalk normalises LAR -> LA, so every Rams player produced
    "SFLAR".replace("LA") = "SFR" -- a team that does not exist. defense_detail then
    found nothing and the opponent adjustment silently did nothing for an entire
    franchise, all season.
    """
    parts = market_ticker.split("-")
    if len(parts) < 2 or not team_code:
        return None
    m = re.match(r"^\d{2}[A-Z]{3}\d{2}([A-Z]{4,8})$", parts[1])
    if not m:
        return None
    split = _split_matchup(m.group(1))
    if not split:
        return None
    away, home = split
    # the ticker uses Kalshi codes; the crosswalk hands us nflverse codes
    norm = {"LAR": "LA", "JAX": "JAC", "WSH": "WAS"}
    a, h = norm.get(away, away), norm.get(home, home)
    # Return the NFLVERSE code: the opponent feeds defense_detail, whose grades are
    # keyed on pbp defteam. Returning Kalshi's "LAR" would silently miss every Rams
    # defensive grade -- the same failure this function was written to fix.
    if team_code == a:
        return h
    if team_code == h:
        return a
    return None


def _game_label(market_ticker: str) -> str | None:
    """26AUG15CARBUF -> "CAR at BUF, Aug 15".

    A strike is meaningless without the game it belongs to: 50 passing yards is
    absurd in September and routine in a preseason game where a starter plays one
    series.
    """
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return None
    m = re.match(r"^\d{2}([A-Z]{3})(\d{2})([A-Z]{4,8})$", parts[1])
    if not m:
        return None
    mon, day, teams = m.groups()
    split = _split_matchup(teams)
    if not split:
        return None
    away, home = split
    return f"{away} at {home}, {mon.title()} {int(day)}"


def _is_preseason(market_ticker: str) -> bool:
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return False
    return any(mo in parts[1][:7].upper() for mo in PRESEASON_MONTHS)


def run(
    archive_glob: str,
    pbp_path: str,
    roster_path: str,
    players_path: str | None = None,
    depth_path: str | None = None,
    injuries_path: str | None = None,
    schedule_path: str | None = None,
    season: int = 2026,
    model_version: str = "nfl-v1",
    mins_before_close: int = 60,
    iterations: int = 20_000,
    seed: int = 20260909,
    allow_preseason: bool = False,
    allow_backups: bool = False,
) -> dict:
    markets = _entry_prices(archive_glob, mins_before_close)
    if not markets:
        return {"markets": 0, "projections": 0, "signals": 0, "skipped": {}}

    roster = pq.read_table(roster_path)
    # Same resolver the depth sync uses, so a promoted backup is projected rather
    # than refused. Injury-driven usage vacancy is the signal Section 5.2 calls most
    # exploitable; refusing it would be the worst possible failure.
    depth = resolve_starters(depth_path, injuries_path) if depth_path else {}
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

    def skip(reason: str):
        skipped[reason] = skipped.get(reason, 0) + 1

    with psycopg.connect(config.DATABASE_URL) as conn:
        for m in markets:
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
            except Exception:
                pctx = None

            adj: list[Adjustment] = []
            if grades is not None and opponent:
                a = defense_adjustment(opponent, m["market_type"],
                                       grades[0], grades[1])
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
                                      pi.targets_per_game, adj,
                                      dispersion=pi.target_dispersion)
                out = project_receiving_yards(vp, pi.catch_rate, pi.yards_per_catch,
                                              [strike], iterations=iterations, seed=seed)
            elif model == "receptions":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.targets_per_game, adj,
                                      dispersion=pi.target_dispersion)
                out = project_receptions(vp, pi.catch_rate, [strike],
                                         iterations=iterations, seed=seed)
            elif model == "rushing_yards":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.carries_per_game, adj,
                                      dispersion=pi.carry_dispersion)
                out = project_rushing_yards(vp, pi.yards_per_carry, [strike],
                                            iterations=iterations, seed=seed)
            elif model == "anytime_td":
                # A different problem from a total: driven by red-zone opportunity,
                # not volume between the 20s.
                ti = load_td_inputs(pbp_path, players_path, xr["gsis_id"], td_baselines)
                mult = 1.0
                for adj_i in adj:
                    mult *= adj_i.multiplier
                td = project_anytime_td(ti, mult, iterations=iterations, seed=seed)
                out = {
                    "mean": td["p_td"], "stdev": 0.0,
                    "percentiles": {}, "p_over_by_strike": {str(strike): td["p_td"]},
                    "explain": [
                        {"step": "red-zone touches / game",
                         "value": round(ti.rz_touches_per_game, 2)},
                        {"step": "TD per red-zone touch", "multiplier": 1.0,
                         "value": round(ti.td_per_rz_touch, 3),
                         "detail": ("player's own rate" if ti.used_own_rate
                                    else f"{ti.position} baseline — too few touches for a personal rate")},
                    ],
                }
            elif model == "passing_yards":
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.attempts_per_game, adj,
                                      dispersion=pi.attempt_dispersion)
                out = project_passing_yards(vp, pi.completion_rate,
                                            pi.yards_per_completion, [strike],
                                            iterations=iterations, seed=seed)
            else:
                vp = VolumeProjection(xr["gsis_id"], m["market_type"],
                                      pi.attempts_per_game, adj,
                                      dispersion=pi.attempt_dispersion)
                out = project_passing_tds(vp, pi.pass_td_rate, [strike],
                                          iterations=iterations, seed=seed)

            p_over = out["p_over_by_strike"][str(strike)]
            if adj:
                n_with_adj += 1
            proj_id = str(uuid.uuid4())
            # volume driver differs by market family; the rationale names it
            volume_metric = {
                "receiving_yards": "targets", "receptions": "targets",
                "anytime_td": "red-zone touches",
                "rushing_yards": "carries",
                "passing_yards": "pass attempts", "passing_tds": "pass attempts",
            }[model]
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
                     m["close_time"], "model", now),
                )
                n_proj += 1

                edge = edge_preview
                cur.execute(
                    """
                    insert into "Signal"
                      (id, "projectionId", "marketTicker", "runTs", side, "modelProb",
                       "marketProb", "feeCents", "edgeCentsNet", "kellyFraction",
                       tier, "sampleN", reason, "modelVersion", "featureAsOf",
                       source, "ingestedAt")
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::"Tier",%s,%s::jsonb,%s,%s,%s,%s)
                    """,
                    (str(uuid.uuid4()), proj_id, m["market_ticker"], now,
                     edge.side,
                     edge.model_prob, edge.market_prob, edge.fee_cents,
                     edge.net_edge_cents, edge.kelly_fraction, edge.tier.value,
                     edge.sample_n, json.dumps(reason), model_version,
                     m["close_time"], "model", now),
                )
                n_sig += 1

    return {"markets": len(markets), "projections": n_proj,
            "signals": n_sig, "skipped": skipped,
            "with_adjustments": n_with_adj}


def main():
    ap = argparse.ArgumentParser(description="Run projections and emit signals")
    ap.add_argument("--archive", default="data/archive/market_snapshots/**/*.parquet")
    ap.add_argument("--pbp", default="data/raw/nflverse/pbp_2025.parquet")
    ap.add_argument("--roster", default="data/raw/nflverse/rosters_weekly_2026.parquet")
    ap.add_argument("--players", default="data/raw/nflverse/players.parquet")
    ap.add_argument("--depth", default="data/raw/nflverse/depth_charts_2026.parquet")
    ap.add_argument("--injuries", default="data/raw/nflverse/injuries_2026.parquet")
    ap.add_argument("--schedule", default="data/raw/nflverse/schedules.parquet")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--allow-backups", action="store_true",
                    help="off by default: a backup's prior usage describes a role he "
                         "no longer holds")
    ap.add_argument("--model-version", default="nfl-v1")
    ap.add_argument("--allow-preseason", action="store_true",
                    help="off by default: preseason usage does not predict anything")
    ap.add_argument("--mins-before-close", type=int, default=60)
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
            season=a.season,
            model_version=a.model_version,
            mins_before_close=a.mins_before_close,
            allow_preseason=a.allow_preseason,
            allow_backups=a.allow_backups,
        )
        run_state["rows"] = r["signals"]
        run_state["meta"] = {"skipped": r["skipped"], "markets": r["markets"]}
    adj_n = r.get("with_adjustments", 0)
    print(f"markets={r['markets']} projections={r['projections']} "
          f"signals={r['signals']} with_adjustments={adj_n}")
    if r["signals"] and adj_n == 0:
        print("  WARNING: no signal carries an adjustment. The matchup layer is "
              "inert -- check that grades loaded and opponents resolved.")
    if r["skipped"]:
        print("skipped:")
        for k, v in sorted(r["skipped"].items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
