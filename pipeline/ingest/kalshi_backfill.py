"""Backfill historical prices from Kalshi candlesticks.

The /markets listing reports volume=null even for markets that genuinely traded, and
carries no price history at all. Candlesticks DO hold both -- verified on a settled
preseason market showing 726 contracts of real volume where the listing showed null.

MEASURED RETENTION: Kalshi keeps settled prop markets reachable for about **22 days**
(on 2026-08-29 the window ran 26AUG06 -> 26AUG27). Inside that window, candlesticks
support 1-MINUTE granularity fetched retroactively.

That makes this job -- not the 15-minute archiver -- the durable path for price
history. A missed archiver run costs nothing recoverable as long as this job runs at
least once inside the retention window. The live archiver's unique contribution is
orderbook DEPTH, which candlesticks do not carry.

Granularity mirrors the adaptive cadence: minute resolution where closing line value
is actually measured, coarse resolution where it is not.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.common import blob, config, db
from pipeline.common.kalshi import KalshiClient, _to_dec
from pipeline.ingest.kalshi_archiver import SCHEMA, _parse_ts, _strike
from pipeline.ingest.kalshi_discovery import NFL_PLAYER_PROPS


def _dec(candle: dict, group: str, field: str):
    g = candle.get(group)
    if isinstance(g, dict):
        return _to_dec(g.get(field))
    return None


# CLV is measured at T-60m, so the final hours need minute resolution; a market
# sitting three weeks from close does not.
FINE_WINDOW_HOURS = 8


def backfill(
    series: dict[str, str],
    lookback_days: int = 21,
    fine: bool = True,
) -> dict:
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
            candles = []
            try:
                # coarse pass over the whole life of the market
                candles = client.candlesticks(
                    series_ticker, ticker, start_ts, end_ts, period_interval=60
                )
                time.sleep(0.1)
                if fine and close:
                    # minute resolution over the window where CLV is measured
                    fine_start = int(close.timestamp()) - FINE_WINDOW_HOURS * 3600
                    fine_end = int(close.timestamp())
                    if fine_end > start_ts:
                        candles += client.candlesticks(
                            series_ticker, ticker,
                            max(fine_start, start_ts), fine_end, period_interval=1
                        )
                        time.sleep(0.1)
            except Exception:
                pass
            if not candles:
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

    # coarse and fine passes overlap, and re-runs repeat rows: dedupe on the
    # natural key so the archive converges instead of accumulating duplicates.
    seen: set[tuple] = set()
    deduped = []
    for r in rows:
        k = (r["market_ticker"], r["ts"])
        if k not in seen:
            seen.add(k)
            deduped.append(r)
    rows = deduped

    tbl = pa.Table.from_pylist(rows, schema=SCHEMA)
    out = config.ARCHIVE_DIR / "market_snapshots" / "backfill"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"candles_{now.strftime('%Y%m%d_%H%M%S')}.parquet"
    pq.write_table(tbl, path, compression="zstd")

    # This file is the durable record of minute-level price history -- the input CLV
    # is computed from. Without this upload it lived only in a 90-day CI artifact,
    # which is exactly the expiry the blob store exists to prevent.
    blob_url = None
    if blob.is_configured():
        try:
            blob_url = blob.put_file(f"market_snapshots/backfill/{path.name}", path)
        except Exception as e:
            errors.append({"stage": "blob_upload", "error": repr(e)[:200]})
    return {
        "rows": tbl.num_rows, "markets": markets_seen,
        "with_prices": with_prices, "errors": errors, "path": str(path),
        "blob_url": blob_url,
    }


def main():
    ap = argparse.ArgumentParser(description="Backfill Kalshi candlestick history")
    ap.add_argument("--days", type=int, default=21,
                    help="Kalshi retains settled prop markets ~22 days")
    ap.add_argument("--coarse-only", action="store_true")
    a = ap.parse_args()
    with db.track("kalshi_backfill") as run:
        r = backfill(NFL_PLAYER_PROPS, a.days, fine=not a.coarse_only)
        run["rows"] = r["rows"]
        run["meta"] = {"markets": r["markets"], "with_prices": r.get("with_prices", 0)}
    print(f"markets={r['markets']} with_prices={r.get('with_prices',0)} rows={r['rows']}")
    print(f"path={r['path']}")
    print(f"blob={'uploaded' if r.get('blob_url') else 'not configured'}")
    if r["errors"]:
        for e in r["errors"][:5]:
            print("  ", e)


if __name__ == "__main__":
    main()
