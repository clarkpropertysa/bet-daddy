"""Kalshi trade-api v2 client.

Verified behaviour (probed 2026-08-28):
  * All market reads are PUBLIC -- /series, /markets, /candlesticks, /orderbook,
    /trades returned 200 with no auth. Auth is only needed for settlements/portfolio.
  * Prices come back as decimal-dollar STRINGS ("0.3100"), not integer cents.
  * volume/open_interest are fixed-point strings (volume_fp, open_interest_fp).
  * The /markets listing reports volume=null even for markets that genuinely traded.
    Real traded volume must be read from candlesticks. Do not trust listing volume.
"""
from __future__ import annotations

import base64
import time
from decimal import Decimal
from typing import Any, Iterator

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.common import config

_UA = "bet-daddy/0.1 (personal research)"


def _to_dec(v: Any) -> Decimal | None:
    """Kalshi returns money as decimal strings. Never parse to float."""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


#: Kalshi renamed every price and size field, appending `_dollars` to prices and `_fp`
#: to quantities: `yes_ask` became `yes_ask_dollars`, `volume` became `volume_fp`, and
#: so on. The old keys are simply ABSENT from the response, so `m.get("yes_ask")`
#: returns None and every market reads as unquoted -- the archive fills with nulls, the
#: board filters them all out, and the UI says "listed but nobody is quoting them yet".
#: Silent, and wrong for as long as nobody checks the exchange by hand.
#:
#: Both spellings are accepted so a rollback, a partial rollout, or a replayed old
#: response keeps working. New name first: it is the one being served.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "yes_bid": ("yes_bid_dollars", "yes_bid"),
    "yes_ask": ("yes_ask_dollars", "yes_ask"),
    "no_bid": ("no_bid_dollars", "no_bid"),
    "no_ask": ("no_ask_dollars", "no_ask"),
    "last_price": ("last_price_dollars", "last_price"),
    "volume": ("volume_fp", "volume"),
    "volume_24h": ("volume_24h_fp", "volume_24h"),
    "open_interest": ("open_interest_fp", "open_interest"),
}


def field(market: dict, name: str):
    """Read a market field under either the current or the legacy key."""
    for key in FIELD_ALIASES.get(name, (name,)):
        if key in market:
            return market[key]
    return None


def has_price_fields(market: dict) -> bool:
    """Does this object carry a price key at all, under EITHER spelling?

    Distinguishes "quoted at nothing" from "we are reading the wrong key". A market
    with no bid is normal; a market with no bid FIELD means the schema moved.
    """
    return any(
        k in market
        for name in ("yes_bid", "yes_ask")
        for k in FIELD_ALIASES[name]
    )


class KalshiClient:
    def __init__(self, base: str | None = None, timeout: int = 30):
        self.base = (base or config.KALSHI_API_BASE).rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": _UA, "Accept": "application/json"})
        self._pk = None

    # ---------- auth (only needed for settlements/portfolio) ----------
    def _private_key(self):
        if self._pk is None:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            if not config.has_kalshi_auth():
                raise RuntimeError(
                    "Kalshi auth not configured. Set KALSHI_KEY_ID and place the private "
                    f"key at {config.KALSHI_PRIVATE_KEY_PATH}. Market reads do not need this."
                )
            self._pk = load_pem_private_key(
                config.KALSHI_PRIVATE_KEY_PATH.read_bytes(), password=None
            )
        return self._pk

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        """RSA-PSS SHA256 over (timestamp_ms + METHOD + path), path excluding query."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        ts = str(int(time.time() * 1000))
        msg = (ts + method.upper() + path).encode()
        sig = self._private_key().sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256.digest_size,  # salt length == digest length
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": config.KALSHI_KEY_ID or "",
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    # ---------- transport ----------
    @retry(
        retry=retry_if_exception_type((requests.RequestException,)),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, path: str, params: dict | None = None, auth: bool = False) -> dict:
        url = f"{self.base}{path}"
        headers = {}
        if auth:
            # signature path includes the /trade-api/v2 prefix, excludes query string
            prefix = self.base.split(".com", 1)[-1] if ".com" in self.base else ""
            headers = self._auth_headers("GET", f"{prefix}{path}")
        r = self.s.get(url, params=params, headers=headers, timeout=self.timeout)
        if r.status_code == 429:
            time.sleep(2)
            r.raise_for_status()
        r.raise_for_status()
        return r.json()

    def paginate(self, path: str, key: str, params: dict, cap: int = 200) -> Iterator[dict]:
        """Follow Kalshi's cursor pagination. `cap` bounds pages, not rows."""
        p = dict(params)
        p.setdefault("limit", 200)
        cursor = None
        for _ in range(cap):
            if cursor:
                p["cursor"] = cursor
            data = self.get(path, p)
            rows = data.get(key) or []
            if not rows:
                return
            yield from rows
            cursor = data.get("cursor")
            if not cursor:
                return

    # ---------- discovery ----------
    def series_list(self, category: str = "Sports") -> list[dict]:
        return self.get("/series", {"category": category}).get("series", [])

    def markets(self, **params) -> Iterator[dict]:
        yield from self.paginate("/markets", "markets", params)

    def candlesticks(
        self, series_ticker: str, market_ticker: str, start_ts: int, end_ts: int,
        period_interval: int = 60,
    ) -> list[dict]:
        """period_interval is minutes: 1, 60, or 1440."""
        return self.get(
            f"/series/{series_ticker}/markets/{market_ticker}/candlesticks",
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval},
        ).get("candlesticks", [])

    def orderbook(self, market_ticker: str, depth: int = 10) -> dict:
        return self.get(f"/markets/{market_ticker}/orderbook", {"depth": depth}).get(
            "orderbook", {}
        )

    def exchange_status(self) -> dict:
        return self.get("/exchange/status")
