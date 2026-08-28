"""Runtime configuration. Reads .env.local, falls back to process env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# .env.local is gitignored and holds real values; .env.example is the committed template.
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(REPO_ROOT / ".env")

KALSHI_API_BASE = os.getenv(
    "KALSHI_API_BASE", "https://api.elections.kalshi.com/trade-api/v2"
).rstrip("/")
KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID") or None

_pk = os.getenv("KALSHI_PRIVATE_KEY_PATH", "~/.kalshi/kalshi_private_key.pem")
KALSHI_PRIVATE_KEY_PATH = Path(_pk).expanduser() if _pk else None

DATA_DIR = Path(os.getenv("BETDADDY_DATA_DIR", REPO_ROOT / "data")).expanduser()
RAW_DIR = DATA_DIR / "raw"
ARCHIVE_DIR = DATA_DIR / "archive"

DATABASE_URL = os.getenv("DATABASE_URL") or None

# Kalshi taker fee: ceil(0.07 * contracts * P * (1-P)) dollars, rounded up per order.
# Verified against series metadata (fee_type=quadratic, fee_multiplier=1) on all KXNFL* series.
KALSHI_TAKER_FEE_RATE = 0.07
KALSHI_MAKER_FEE_RATE = 0.0175


def has_kalshi_auth() -> bool:
    """Auth is only needed for settlements/portfolio. All market reads are public."""
    return bool(
        KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH and KALSHI_PRIVATE_KEY_PATH.exists()
    )


for _d in (RAW_DIR, ARCHIVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
