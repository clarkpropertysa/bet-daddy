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

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.common import blob, config, db
from pipeline.common.cadence import is_due
from pipeline.common.kalshi import KalshiClient, field, has_price_fields, _to_dec
from pipeline.ingest.kalshi_discovery import NBA_PLAYER_PROPS, NFL_PLAYER_PROPS

# Decimal, not float: the whole edge is ~1.75c wide and float rounding is not
# acceptable at that scale (DECISIONS.md D3).
_PRICE = pa.decimal128(6, 4)
_QTY = pa.decimal128(18, 4)
_TS = pa.timestamp("us", tz="UTC")

SCHEMA = pa.schema([
    ("market_ticker", pa.string()),
    ("series_ticker", pa.string()),
    ("event_ticker", pa.string()),
    ("sport", pa.string()),
    ("market_type", pa.string()),
    ("ts", _TS),
    ("yes_bid", _PRICE),
    ("yes_ask", _PRICE),
    ("no_ask", _PRICE),
    ("last_price", _PRICE),
    ("volume", _QTY),
    ("open_interest", _QTY),
    ("strike", pa.float64()),
    ("status", pa.string()),
    ("close_time", _TS),
    ("mins_to_close", pa.int64()),
    ("result", pa.string()),
    ("orderbook", pa.string()),
    ("source", pa.string()),
])


def _parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _strike(market: dict) -> float | None:
    """The real strike, from `floor_strike` -- NOT the ticker suffix.

    They differ by exactly the amount that matters. A receptions market titled
    "Rhamondre Stevenson: 8+" has ticker `...-8` and `floor_strike = 7.5`, because it
    settles on MORE THAN 7.5. Parsing the suffix gave 8 and the simulator computes a
    strict P(> strike), so every count market was priced as P(>= 9) while the market
    settles P(>= 8) -- a systematic off-by-one on every receptions and touchdown line,
    always in the same direction.

    Falls back to the suffix only when floor_strike is absent, so an older archived
    response still parses.
    """
    fs = market.get("floor_strike")
    if fs is not None:
        try:
            return float(fs)
        except (TypeError, ValueError):
            pass
    tail = (market.get("ticker") or "").rsplit("-", 1)[-1]
    try:
        return float(tail)
    except ValueError:
        return None


def _last_seen() -> dict[str, datetime]:
    """Most recent snapshot ts per market, read from the Parquet archive itself.

    The archive is the source of truth for what we already have -- no side state to
    drift out of sync with the data.
    """
    root = config.ARCHIVE_DIR / "market_snapshots"
    if not any(root.rglob("*.parquet")):
        return {}
    # epoch seconds, not a timestamp object: DuckDB needs pytz to materialise a
    # tz-aware datetime, and an extra dependency for an integer is not worth it.
    rows = duckdb.connect().execute(
        f"""select market_ticker, max(epoch(ts))
            from read_parquet('{root}/**/*.parquet') group by 1"""
    ).fetchall()
    return {t: datetime.fromtimestamp(e, tz=timezone.utc) for t, e in rows}


def snapshot(
    sports: tuple[str, ...] = ("nfl", "nba"),
    with_orderbook: bool = True,
    orderbook_cap: int = 400,
    adaptive: bool = True,
) -> dict:
    client = KalshiClient()
    now = datetime.now(timezone.utc)
    last = _last_seen() if adaptive else {}

    series_map: dict[str, tuple[str, str]] = {}
    if "nfl" in sports:
        series_map |= {k: ("nfl", v) for k, v in NFL_PLAYER_PROPS.items()}
    if "nba" in sports:
        series_map |= {k: ("nba", v) for k, v in NBA_PLAYER_PROPS.items()}

    rows, errors, ob_calls, skipped = [], [], 0, 0
    # Markets whose response carried a price KEY at all, under either
    # spelling. Zero of these across a full slate means the schema moved.
    priced_fields = 0

    for series_ticker, (sport, market_type) in series_map.items():
        try:
            markets = list(client.markets(series_ticker=series_ticker, status="open"))
        except Exception as e:  # one dead series must not kill the run
            errors.append({"series": series_ticker, "error": repr(e)})
            continue

        for m in markets:
            ticker = m.get("ticker")
            close = _parse_ts(m.get("close_time"))
            mtc = int((close - now).total_seconds() // 60) if close else None

            if adaptive:
                prev = last.get(ticker)
                elapsed = (now - prev).total_seconds() / 60 if prev else None
                if not is_due(mtc, elapsed):
                    skipped += 1
                    continue

            # Read through the alias table: Kalshi renamed these to *_dollars and the
            # old keys are absent, so a direct m.get() silently returns None for every
            # market and the whole archive fills with nulls.
            yb, ya = _to_dec(field(m, "yes_bid")), _to_dec(field(m, "yes_ask"))
            # The real NO-side ask. compute_edge otherwise infers it as 1 - yes_ask,
            # which is fiction on a one-sided book: Stevenson 8+ shows yes_ask 0.98
            # with no_ask 1.00, so the inferred 0.02 implied a 97c edge on a trade
            # that cannot be executed at any price.
            na = _to_dec(field(m, "no_ask"))
            if has_price_fields(m):
                priced_fields += 1

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
                "no_ask": na,
                "last_price": _to_dec(field(m, "last_price")),
                "volume": _to_dec(field(m, "volume")),
                "open_interest": _to_dec(field(m, "open_interest")),
                "strike": _strike(m),
                "status": m.get("status"),
                "close_time": close,
                "mins_to_close": mtc,
                "result": m.get("result") or None,
                "orderbook": ob_json,
                "source": "kalshi:/markets",
            })

    if not rows:
        return {"rows": 0, "skipped": skipped, "errors": errors, "path": None}

    df = pa.Table.from_pylist(rows, schema=SCHEMA)
    day = now.strftime("%Y-%m-%d")
    out_dir = config.ARCHIVE_DIR / "market_snapshots" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"snap_{now.strftime('%H%M%S')}.parquet"
    pq.write_table(df, path, compression="zstd")

    # Parquet to disk FIRST, remote second. A blob outage must never cost a
    # snapshot, and the local file is what the next run reads for cadence.
    blob_url = None
    if blob.is_configured():
        try:
            blob_url = blob.put_file(
                f"market_snapshots/date={day}/{path.name}", path)
        except Exception as e:  # durability is best-effort; the run still succeeded
            errors.append({"stage": "blob_upload", "error": repr(e)[:200]})

    quoted = sum(
        1 for r in rows if r["yes_bid"] is not None or r["yes_ask"] is not None
    )
    # SCHEMA DRIFT GUARD. "Nobody is quoting" and "we are reading the wrong key" look
    # identical from the outside -- both produce a column of nulls -- and the second one
    # cost a launch. A market with no bid is ordinary; a slate of markets with no bid
    # FIELD is the exchange having renamed something.
    if rows and priced_fields == 0:
        errors.append({
            "stage": "schema_drift",
            "error": (
                f"none of {len(rows)} markets carried a recognised price field. "
                f"Kalshi has likely renamed them again -- check the raw response and "
                f"extend FIELD_ALIASES in pipeline/common/kalshi.py."
            ),
        })
    return {
        "rows": df.num_rows,
        "quoted": quoted,
        "orderbooks": ob_calls,
        "skipped": skipped,
        "errors": errors,
        "priced_fields": priced_fields,
        "path": str(path),
        "blob_url": blob_url,
    }


def main():
    ap = argparse.ArgumentParser(description="Archive Kalshi player-prop market snapshots")
    ap.add_argument("--sports", default="nfl,nba")
    ap.add_argument("--no-orderbook", action="store_true")
    ap.add_argument("--no-adaptive", action="store_true",
                    help="snapshot every market regardless of cadence")
    a = ap.parse_args()

    started = time.time()
    # Records the outcome either way, so the UI can report staleness instead of
    # silently serving an old snapshot as if it were current (Sections 6 and 12).
    with db.track("kalshi_archiver") as run:
        r = snapshot(
            sports=tuple(s.strip() for s in a.sports.split(",") if s.strip()),
            with_orderbook=not a.no_orderbook,
            adaptive=not a.no_adaptive,
        )
        run["rows"] = r["rows"]
        run["meta"] = {
            "skipped": r.get("skipped", 0),
            "quoted": r.get("quoted", 0),
            "blob": bool(r.get("blob_url")),
            "errors": len(r.get("errors") or []),
        }

    took = time.time() - started
    print(f"rows={r['rows']} skipped={r.get('skipped', 0)} quoted={r.get('quoted', 0)} "
          f"orderbooks={r.get('orderbooks', 0)} took={took:.1f}s")
    print(f"path={r['path']}")
    print(f"blob={'uploaded' if r.get('blob_url') else 'not configured'}")
    print(f"run_recorded={'yes' if db.is_configured() else 'no db configured'}")
    if r["errors"]:
        print(f"ERRORS ({len(r['errors'])}):")
        for e in r["errors"]:
            print("  ", e)


if __name__ == "__main__":
    main()
