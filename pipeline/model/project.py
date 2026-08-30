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
import uuid
from datetime import datetime, timezone

import duckdb
import pyarrow.parquet as pq

from pipeline.common import config, db
from pipeline.features.crosswalk import build_crosswalk
from pipeline.model.features_for_projection import (
    InsufficientHistory,
    load_player_inputs,
)
from pipeline.model.adjustments import defense_adjustment
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


def _is_preseason(market_ticker: str) -> bool:
    parts = market_ticker.split("-")
    if len(parts) < 2:
        return False
    return any(mo in parts[1][:7].upper() for mo in PRESEASON_MONTHS)


def run(
    archive_glob: str,
    pbp_path: str,
    roster_path: str,
    model_version: str,
    mins_before_close: int = 60,
    iterations: int = 20_000,
    seed: int = 20260909,
    defense_grades: tuple | None = None,
    allow_preseason: bool = False,
) -> dict:
    markets = _entry_prices(archive_glob, mins_before_close)
    if not markets:
        return {"markets": 0, "projections": 0, "signals": 0, "skipped": {}}

    roster = pq.read_table(roster_path)
    xw = build_crosswalk([m["market_ticker"] for m in markets], roster)
    by_key = {
        r["raw_key"]: r for r in xw.to_pylist() if r["gsis_id"] is not None
    }

    import psycopg

    now = datetime.now(timezone.utc)
    skipped: dict[str, int] = {}
    n_proj = n_sig = 0

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

            model = MARKET_MODEL.get(m["market_type"])
            if not model:
                skip("unmodelled_market"); continue

            try:
                pi = load_player_inputs(pbp_path, xr["gsis_id"])
            except InsufficientHistory:
                skip("insufficient_history"); continue

            strike = m["strike"]
            if strike is None:
                skip("no_strike"); continue

            adj: list[Adjustment] = []
            if defense_grades is not None and m.get("opponent"):
                a = defense_adjustment(m["opponent"], m["market_type"],
                                       defense_grades[0], defense_grades[1])
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
            proj_id = str(uuid.uuid4())
            # volume driver differs by market family; the rationale names it
            volume_metric = {
                "receiving_yards": "targets", "receptions": "targets",
                "rushing_yards": "carries",
                "passing_yards": "pass attempts", "passing_tds": "pass attempts",
            }[model]
            baseline_vol = vp.baseline
            edge_preview = compute_edge(p_over, m["yes_ask"])

            divergence = abs(p_over - float(m["yes_ask"]))
            implausible = divergence > IMPLAUSIBLE_DIVERGENCE
            if implausible:
                skip("implausible_divergence_flagged")

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
            "signals": n_sig, "skipped": skipped}


def main():
    ap = argparse.ArgumentParser(description="Run projections and emit signals")
    ap.add_argument("--archive", default="data/archive/market_snapshots/**/*.parquet")
    ap.add_argument("--pbp", default="data/raw/nflverse/pbp_2025.parquet")
    ap.add_argument("--roster", default="data/raw/nflverse/rosters_weekly_2026.parquet")
    ap.add_argument("--model-version", default="nfl-v1")
    ap.add_argument("--allow-preseason", action="store_true",
                    help="off by default: preseason usage does not predict anything")
    ap.add_argument("--mins-before-close", type=int, default=60)
    a = ap.parse_args()

    with db.track("projection") as run_state:
        r = run(a.archive, a.pbp, a.roster, a.model_version, a.mins_before_close,
                allow_preseason=a.allow_preseason)
        run_state["rows"] = r["signals"]
        run_state["meta"] = {"skipped": r["skipped"], "markets": r["markets"]}
    print(f"markets={r['markets']} projections={r['projections']} signals={r['signals']}")
    if r["skipped"]:
        print("skipped:")
        for k, v in sorted(r["skipped"].items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
