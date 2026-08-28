"""Discover Kalshi player-prop series programmatically.

Section 12: never hardcode series tickers -- Kalshi's taxonomy changes. This module
discovers them from /series and classifies by ticker family, persisting results so a
taxonomy change shows up as a diff rather than a silent zero-row pipeline.

Probed 2026-08-28: 3585 Sports series, 290 KXNFL*, 204 KXNBA*.
Tags are sport-level ("Football"/"Basketball"), NOT league-level -- there is no "NFL"
tag, so ticker-prefix classification is required.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pipeline.common import config
from pipeline.common.kalshi import KalshiClient

# Per-game PLAYER prop families only. Season-long, leader, H2H and team markets are
# excluded: different modelling problem, and H2H has no single-player strike.
NFL_PLAYER_PROPS = {
    "KXNFLPASSYDS": "pass_yds",
    "KXNFLRECYDS": "rec_yds",
    "KXNFLRSHYDS": "rush_yds",
    "KXNFLREC": "receptions",
    "KXNFLPASSTDS": "pass_tds",
    "KXNFLANYTD": "anytime_td",
    "KXNFLPASSINT": "pass_int",
    "KXNFLSACK": "sacks",
    "KXNFLLONGESTREC": "longest_rec",
}
NBA_PLAYER_PROPS = {
    "KXNBAPTS": "points",
    "KXNBAREB": "rebounds",
    "KXNBAAST": "assists",
    "KXNBA3PT": "threes",
    "KXNBAPRA": "pra",
    "KXNBABLK": "blocks",
    "KXNBASTL": "steals",
}

_EXCLUDE = re.compile(r"H2H|SEASON|LEADER|RECORD|WEEKMOST|MOST|ALLGAMES|SERIES|PLAYOFF", re.I)


def discover(client: KalshiClient | None = None) -> dict:
    client = client or KalshiClient()
    series = client.series_list("Sports")

    known = {**{k: ("nfl", v) for k, v in NFL_PLAYER_PROPS.items()},
             **{k: ("nba", v) for k, v in NBA_PLAYER_PROPS.items()}}

    found, unknown_candidates = [], []
    by_ticker = {s["ticker"]: s for s in series}

    for ticker, (sport, market_type) in known.items():
        s = by_ticker.get(ticker)
        found.append({
            "ticker": ticker,
            "sport": sport,
            "market_type": market_type,
            "title": (s or {}).get("title"),
            "fee_type": (s or {}).get("fee_type"),
            "fee_multiplier": (s or {}).get("fee_multiplier"),
            "present": s is not None,
        })

    # Surface NEW player-prop-looking series we don't yet map, so taxonomy drift is loud.
    pat = re.compile(r"^KX(NFL|NBA)")
    for s in series:
        t = s["ticker"]
        if pat.match(t) and t not in known and not _EXCLUDE.search(t):
            unknown_candidates.append({"ticker": t, "title": s.get("title")})

    result = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "sports_series_total": len(series),
        "series": found,
        "unmapped_candidates": unknown_candidates,
    }
    out = config.DATA_DIR / "kalshi_series.json"
    out.write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = discover()
    print(f"sports series total: {r['sports_series_total']}")
    print(f"\nmapped player-prop series ({len(r['series'])}):")
    for s in r["series"]:
        flag = "OK " if s["present"] else "MISSING"
        print(f"  [{flag}] {s['ticker']:<20} {s['sport']:<4} {s['market_type']:<12} "
              f"fee={s['fee_type']}/{s['fee_multiplier']}")
    print(f"\nunmapped KXNFL*/KXNBA* candidates: {len(r['unmapped_candidates'])}")
