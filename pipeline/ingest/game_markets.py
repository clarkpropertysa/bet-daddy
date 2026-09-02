"""Kalshi game markets vs the sportsbook consensus. REFERENCE ONLY.

DECISIONS.md D8 deferred paid odds data with a revisit trigger -- "revisit if the archive
shows Kalshi pricing diverging from consensus" -- that could not be evaluated, because
nothing measured the divergence. This measures it, for nothing:

- Kalshi lists NFL game markets (`KXNFLGAME`), one binary per team, public reads.
- nflverse `schedules.parquet` already carries closing Vegas moneylines, and the Slate
  already renders its spreads and totals.

Game markets carry no player, so none of the cross-source name resolution that made the
paid path expensive applies here. And nothing this job writes is ever a Signal: it cannot
be bet, sized, or fee-adjusted, which is exactly why the exchange assumptions in
signal.py and fees.py do not have to change to accommodate it.
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import duckdb

from pipeline.common import config, db, tickers
from pipeline.common.kalshi import KalshiClient, field
from pipeline.features.consensus import GameComparison, compare_game, summarise

SERIES = "KXNFLGAME"
SOURCE = "kalshi:/markets+nflverse"

# Same bounds the projection enforces: a 0c or 100c ask is an empty or one-sided book
# reported as a number, not a price.
MIN_ASK = 0.01
MAX_ASK = 0.99


def _vegas_lines(schedule_path: str, season: int) -> dict[tuple[str, str, str], dict]:
    """(gameday, away, home) -> game id and moneylines, in nflverse codes.

    Keyed on the date as well as the teams because division rivals meet twice a season
    and a (away, home) key alone would silently collapse the two games into one.
    """
    con = duckdb.connect()
    rows = con.execute(f"""
        select game_id, gameday, away_team, home_team, away_moneyline, home_moneyline,
               spread_line, total_line
        from read_parquet('{schedule_path}')
        where season = {int(season)} and game_type = 'REG'
    """).fetchall()
    return {
        (str(r[1]), r[2], r[3]): {
            "game_id": r[0], "away_ml": r[4], "home_ml": r[5],
            "spread": r[6], "total": r[7],
        }
        for r in rows
    }


def _kalshi_game_quotes(client: KalshiClient) -> dict[str, dict]:
    """event ticker -> {team code: ask}, for every open game market."""
    out: dict[str, dict] = {}
    for m in client.markets(series_ticker=SERIES, status="open"):
        ticker = m.get("ticker") or ""
        parts = ticker.split("-")
        if len(parts) < 3:
            continue
        ask = field(m, "yes_ask")   # renamed to yes_ask_dollars
        try:
            ask = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            ask = None
        # Kalshi returns dollars on this endpoint, but has returned cents elsewhere.
        if ask is not None and ask > 1:
            ask = ask / 100.0
        out.setdefault(parts[1], {})[parts[2]] = ask
    return out


def collect(schedule_path: str, season: int) -> dict:
    """One row per upcoming game: Kalshi's de-vigged price against the consensus."""
    client = KalshiClient()
    quotes = _kalshi_game_quotes(client)
    vegas = _vegas_lines(schedule_path, season)
    now = datetime.now(timezone.utc)

    rows: list[dict] = []
    comparisons: list[GameComparison] = []
    skipped: dict[str, int] = {}

    def skip(reason: str):
        skipped[reason] = skipped.get(reason, 0) + 1

    for event_ticker, by_team in quotes.items():
        ev = tickers.parse_event(f"{SERIES}-{event_ticker}-X")
        if not ev:
            skip("unparseable_event"); continue
        if ev.is_preseason:
            skip("preseason"); continue

        v = vegas.get((ev.date, ev.away, ev.home))
        if not v:
            skip("no_schedule_match"); continue

        home_ask = by_team.get(ev.raw_home)
        away_ask = by_team.get(ev.raw_away)
        quoted = (
            home_ask is not None and away_ask is not None
            and MIN_ASK < home_ask < MAX_ASK and MIN_ASK < away_ask < MAX_ASK
        )

        if not quoted:
            # Recorded rather than dropped: "listed but nobody is quoting it" is the
            # normal state well before kickoff, and must stay distinguishable from
            # "the job did not run".
            rows.append({"game_id": v["game_id"], "ts": now, "quoted": False,
                         "k": None, "vg": None, "diff": None, "ko": None, "vo": None})
            skip("unquoted")
            continue

        if v["home_ml"] is None or v["away_ml"] is None:
            skip("no_vegas_moneyline"); continue

        c = compare_game(home_ask, away_ask, v["home_ml"], v["away_ml"])
        comparisons.append(c)
        rows.append({
            "game_id": v["game_id"], "ts": now, "quoted": True,
            "k": c.kalshi_prob_home, "vg": c.vegas_prob_home, "diff": c.diff_pts,
            "ko": c.kalshi_overround, "vo": c.vegas_overround,
        })

    return {"rows": rows, "summary": summarise(comparisons),
            "events": len(quotes), "skipped": skipped}


def write(rows: list[dict]) -> int:
    import psycopg

    if not rows:
        return 0
    params = [
        (str(uuid.uuid4()), r["game_id"], r["ts"], r["k"], r["vg"], r["diff"],
         r["ko"], r["vo"], r["quoted"], SOURCE)
        for r in rows
    ]
    with psycopg.connect(config.DATABASE_URL) as c, c.cursor() as cur:
        cur.executemany(
            """
            insert into "GameMarketCompare"
              (id, "gameId", ts, "kalshiProbHome", "vegasProbHome", "diffPts",
               "kalshiOverround", "vegasOverround", "kalshiQuoted", source)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict ("gameId", ts) do update set
              "kalshiProbHome" = excluded."kalshiProbHome",
              "vegasProbHome"  = excluded."vegasProbHome",
              "diffPts"        = excluded."diffPts",
              "kalshiQuoted"   = excluded."kalshiQuoted"
            """,
            params,
        )
    return len(params)


def main():
    ap = argparse.ArgumentParser(
        description="Compare Kalshi game markets to the sportsbook consensus (reference only)"
    )
    ap.add_argument("--schedule", default="data/raw/nflverse/schedules.parquet")
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()

    with db.track("game_markets") as run:
        r = collect(a.schedule, a.season)
        n = write(r["rows"])
        run["rows"] = n
        run["meta"] = {"events": r["events"], "summary": r["summary"],
                       "skipped": r["skipped"]}

    s = r["summary"]
    print(f"events={r['events']} rows={n} compared={s['n']}")
    if s["n"]:
        print(f"  mean divergence  {s['mean_diff_pts']:+.2f} pts (signed)")
        print(f"  mean |divergence| {s['mean_abs_diff_pts']:.2f} pts")
        print(f"  worst game        {s['max_abs_diff_pts']:.2f} pts")
        print("  This is DECISIONS.md D8's revisit criterion. A large mean absolute "
              "divergence is the evidence that paid prop consensus would be worth "
              "buying; a small one is the evidence it would not.")
    else:
        print("  No game was quoted on both sides, so there is nothing to compare yet. "
              "Kalshi lists these markets well before anyone makes a price on them.")
    if r["skipped"]:
        print("skipped:")
        for k, v in sorted(r["skipped"].items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
