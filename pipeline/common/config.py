"""Runtime configuration. Reads .env.local, falls back to process env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    """Merge .env.local over .env, ignoring EMPTY assignments.

    Not two load_dotenv() calls. load_dotenv does not override a variable that is
    already set, and it counts an empty assignment as set -- so a bare
    `DATABASE_URL=""` in .env.local (which is what `vercel env pull` leaves behind for
    a variable it cannot resolve) permanently shadowed the real value in .env. The
    result was silent: is_configured() returned False, every database write was
    skipped by design, and jobs reported success having written nothing.

    An empty value means "no opinion", not "the empty string".
    """
    merged = dict(dotenv_values(REPO_ROOT / ".env"))
    for k, v in dotenv_values(REPO_ROOT / ".env.local").items():
        if v:
            merged[k] = v
    for k, v in merged.items():
        # The real process environment still wins -- CI passes secrets that way.
        if not os.environ.get(k):
            os.environ[k] = v


_load_env()

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
