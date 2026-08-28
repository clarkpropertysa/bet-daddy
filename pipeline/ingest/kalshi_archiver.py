"""Kalshi market snapshot archiver -- the highest-priority job in the repo.

Kalshi's public API does NOT retain settled player-prop markets from prior seasons.
Probed 2026-08-28: every settled KXNFLPASSYDS market was from the last few days
(26AUG), and KXNBAPTS/REB/PRA returned zero. The 2025 season's prop prices are gone.

Consequence: price history that is not captured now can never be recovered or bought.
This job is append-only and runs every 15 minutes. It writes Parquet locally first so
that a missing/erroring database never costs us data (Section 6: raw layer is Parquet,
Neon holds engineered outputs only).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import polars as pl

from pipeline.common import config
from pipeline.common.kalshi import KalshiClient, _to_dec
from pipeline.ingest.kalshi_discovery import NBA_PLAYER_PROPS, NFL_PLAYER_PROPS

SCHEMA = {
    "market_ticker": pl.Utf8,
    "series_ticker": pl.Utf8,
    "event_ticker": pl.Utf8,
    "sport": pl.Utf8,
    "market_type": pl.Utf8,
    "ts": pl.Datetime(time_unit="us", time_zone="UTC"),
    "yes_bid": pl.Decimal(precision=6, scale=4),
    "yes_ask": pl.Decimal(precision=6, scale=4),
    "last_price": pl.Decimal(precision=6, scale=4),
    "volume": pl.Decimal(precision=18, scale=4),
    "open_interest": pl.Decimal(precision=18, scale=4),
    "strike": pl.Float64,
    "status": pl.Utf8,
    "close_time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "mins_to_close": pl.Int64,
    "result": pl.Utf8,
    "orderbook": pl.Utf8,
    "source": pl.Utf8,
}


def _parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _strike(ticker: str) -> float | None:
    """Strike is the final dash-delimited segment: ...-SFBPURDY13-350 -> 350."""
    tail = ticker.rsplit("-", 1)[-1]
    try:
        return float(tail)
    except ValueError:
        return None


def snapshot(
    sports: tuple[str, ...] = ("nfl", "nba"),
    with_orderbook: bool = True,
    orderbook_cap: int = 400,
) -> dict:
    client = KalshiClient()
    now = datetime.now(timezone.utc)

    series_map: dict[str, tuple[str, str]] = {}
    if "nfl" in sports:
        series_map |= {k: ("nfl", v) for k, v in NFL_PLAYER_PROPS.items()}
    if "nba" in sports:
        series_map |= {k: ("nba", v) for k, v in NBA_PLAYER_PROPS.items()}

    rows, errors, ob_calls = [], [], 0

    for series_ticker, (sport, market_type) in series_map.items():
        try:
            markets = list(client.markets(series_ticker=series_ticker, status="open"))
        except Exception as e:  # one dead series must not kill the run
            errors.append({"series": series_ticker, "error": repr(e)})
            continue

        for m in markets:
            ticker = m.get("ticker")
            close = _parse_ts(m.get("close_time"))
            yb, ya = _to_dec(m.get("yes_bid")), _to_dec(m.get("yes_ask"))

            ob_json = None
            # Only spend an API call where a quote actually exists. The listing's
            # volume field is unreliable (null even for traded markets), so quote
            # presence -- not volume -- is the liquidity signal.
            if with_orderbook and (yb is not None or ya is not None) and ob_calls < orderbook_cap:
                try:
                    ob_json = json.dumps(client.orderbook(ticker, depth=10))
                    ob_calls += 1
                    time.sleep(0.12)  # stay well inside rate limits
                except Exception:
                    ob_json = None

            rows.append({
                "market_ticker": ticker,
                "series_ticker": series_ticker,
                "event_ticker": m.get("event_ticker"),
                "sport": sport,
                "market_type": market_type,
                "ts": now,
                "yes_bid": yb,
                "yes_ask": ya,
                "last_price": _to_dec(m.get("last_price")),
                "volume": _to_dec(m.get("volume")),
                "open_interest": _to_dec(m.get("open_interest")),
                "strike": _strike(ticker or ""),
                "status": m.get("status"),
                "close_time": close,
                "mins_to_close": int((close - now).total_seconds() // 60) if close else None,
                "result": m.get("result") or None,
                "orderbook": ob_json,
                "source": "kalshi:/markets",
            })

    if not rows:
        return {"rows": 0, "errors": errors, "path": None}

    df = pl.DataFrame(rows, schema=SCHEMA)
    day = now.strftime("%Y-%m-%d")
    out_dir = config.ARCHIVE_DIR / "market_snapshots" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"snap_{now.strftime('%H%M%S')}.parquet"
    df.write_parquet(path, compression="zstd")

    quoted = df.filter(
        pl.col("yes_bid").is_not_null() | pl.col("yes_ask").is_not_null()
    ).height
    return {
        "rows": df.height,
        "quoted": quoted,
        "orderbooks": ob_calls,
        "errors": errors,
        "path": str(path),
    }


def main():
    ap = argparse.ArgumentParser(description="Archive Kalshi player-prop market snapshots")
    ap.add_argument("--sports", default="nfl,nba")
    ap.add_argument("--no-orderbook", action="store_true")
    a = ap.parse_args()

    started = time.time()
    r = snapshot(
        sports=tuple(s.strip() for s in a.sports.split(",") if s.strip()),
        with_orderbook=not a.no_orderbook,
    )
    took = time.time() - started
    print(f"rows={r['rows']} quoted={r.get('quoted', 0)} orderbooks={r.get('orderbooks', 0)} "
          f"took={took:.1f}s")
    print(f"path={r['path']}")
    if r["errors"]:
        print(f"ERRORS ({len(r['errors'])}):")
        for e in r["errors"]:
            print("  ", e)


if __name__ == "__main__":
    main()
