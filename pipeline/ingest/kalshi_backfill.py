"""Backfill historical prices from Kalshi candlesticks.

The /markets listing reports volume=null even for markets that genuinely traded, and
carries no price history at all. Candlesticks DO hold both -- verified on a settled
preseason market showing 726 contracts of real volume where the listing showed null.

Kalshi retains only recently-settled prop markets (D1), so this reaches the current
preseason and nothing earlier. That is precisely why the forward archiver matters: this
is the last of the recoverable history, and it is days old, not seasons.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.common import config, db
from pipeline.common.kalshi import KalshiClient, _to_dec
from pipeline.ingest.kalshi_archiver import SCHEMA, _parse_ts, _strike
from pipeline.ingest.kalshi_discovery import NFL_PLAYER_PROPS


def _dec(candle: dict, group: str, field: str):
    g = candle.get(group)
    if isinstance(g, dict):
        return _to_dec(g.get(field))
    return None


def backfill(series: dict[str, str], lookback_days: int = 14) -> dict:
    client = KalshiClient()
    now = datetime.now(timezone.utc)
    end_ts = int(now.timestamp())
    start_ts = end_ts - lookback_days * 86400

    rows, errors, markets_seen, with_prices = [], [], 0, 0

    for series_ticker, market_type in series.items():
        try:
            settled = list(client.markets(series_ticker=series_ticker, status="settled"))
        except Exception as e:
            errors.append({"series": series_ticker, "error": repr(e)[:200]})
            continue

        for m in settled:
            ticker = m.get("ticker")
            close = _parse_ts(m.get("close_time"))
            markets_seen += 1
            try:
                candles = client.candlesticks(
                    series_ticker, ticker, start_ts, end_ts, period_interval=60
                )
                time.sleep(0.1)
            except Exception:
                continue
            if not candles:
                continue
            with_prices += 1

            for c in candles:
                ts = datetime.fromtimestamp(int(c["end_period_ts"]), tz=timezone.utc)
                rows.append({
                    "market_ticker": ticker,
                    "series_ticker": series_ticker,
                    "event_ticker": m.get("event_ticker"),
                    "sport": "nfl",
                    "market_type": market_type,
                    "ts": ts,
                    "yes_bid": _dec(c, "yes_bid", "close_dollars"),
                    "yes_ask": _dec(c, "yes_ask", "close_dollars"),
                    "last_price": _dec(c, "price", "close_dollars"),
                    "volume": _to_dec(c.get("volume_fp")),
                    "open_interest": _to_dec(c.get("open_interest_fp")),
                    "strike": _strike(ticker or ""),
                    "status": "settled",
                    "close_time": close,
                    "mins_to_close": int((close - ts).total_seconds() // 60) if close else None,
                    "result": m.get("result") or None,
                    "orderbook": None,
                    "source": "kalshi:/candlesticks",
                })

    if not rows:
        return {"rows": 0, "markets": markets_seen, "errors": errors, "path": None}

    tbl = pa.Table.from_pylist(rows, schema=SCHEMA)
    out = config.ARCHIVE_DIR / "market_snapshots" / "backfill"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"candles_{now.strftime('%Y%m%d_%H%M%S')}.parquet"
    pq.write_table(tbl, path, compression="zstd")
    return {
        "rows": tbl.num_rows, "markets": markets_seen,
        "with_prices": with_prices, "errors": errors, "path": str(path),
    }


def main():
    ap = argparse.ArgumentParser(description="Backfill Kalshi candlestick history")
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    with db.track("kalshi_backfill") as run:
        r = backfill(NFL_PLAYER_PROPS, a.days)
        run["rows"] = r["rows"]
        run["meta"] = {"markets": r["markets"], "with_prices": r.get("with_prices", 0)}
    print(f"markets={r['markets']} with_prices={r.get('with_prices',0)} rows={r['rows']}")
    print(f"path={r['path']}")
    if r["errors"]:
        for e in r["errors"][:5]:
            print("  ", e)


if __name__ == "__main__":
    main()
