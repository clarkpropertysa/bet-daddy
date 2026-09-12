"""Vercel Blob storage for the Parquet archive.

The market archive is the only irreplaceable asset in this system: Kalshi does not
retain settled prop markets across seasons (DECISIONS.md D1), so a snapshot not
captured now can never be bought back. In CI the ONLY persistence was a GitHub
artifact with 90-day retention, which would have started silently dropping data in
late November -- mid-season. This gives it a durable home.

Uses the Blob REST API directly rather than shelling out to the Node SDK. Header
names were read from the SDK source, not guessed: the access header is
`x-vercel-blob-access`, and omitting it fails with a misleading "Cannot use public
access on a private store" even when you did not ask for public access.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BLOB_API = "https://blob.vercel-storage.com"
API_VERSION = "7"


class BlobNotConfigured(RuntimeError):
    pass


def _token() -> str:
    tok = os.getenv("BLOB_READ_WRITE_TOKEN")
    if not tok:
        raise BlobNotConfigured(
            "BLOB_READ_WRITE_TOKEN not set. Run `vercel env pull .env` locally, or add "
            "it as a GitHub Actions secret for CI."
        )
    return tok


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def put(pathname: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to the private blob store. Returns the blob URL.

    Overwrite is allowed so a re-run of the same snapshot minute is idempotent
    rather than accumulating duplicates.
    """
    r = requests.put(
        f"{BLOB_API}/{pathname.lstrip('/')}",
        headers={
            "authorization": f"Bearer {_token()}",
            "x-api-version": API_VERSION,
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-vercel-blob-access": "private",
        },
        data=data,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["url"]


def put_file(pathname: str, path: Path, content_type: str = "application/vnd.apache.parquet") -> str:
    return put(pathname, path.read_bytes(), content_type)


def is_configured() -> bool:
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN"))


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _page(prefix: str, cursor: str | None, limit: int) -> dict:
    url = f"{BLOB_API}/?prefix={prefix}&limit={limit}"
    if cursor:
        url += f"&cursor={cursor}"
    r = requests.get(
        url,
        headers={"authorization": f"Bearer {_token()}", "x-api-version": API_VERSION},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def listing(prefix: str = "market_snapshots/", limit: int = 1000) -> list[dict]:
    """Every blob under `prefix`, following the cursor. Verified against the live API."""
    out: list[dict] = []
    cursor = None
    while True:
        page = _page(prefix, cursor, limit)
        out.extend(page.get("blobs", []))
        if not page.get("hasMore"):
            return out
        cursor = page.get("cursor")


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def fetch(entry: dict, dest: Path) -> int:
    """Download one listed blob to `dest`. Returns bytes written.

    The store is private, so the download carries the same bearer token the upload
    did -- a bare GET of the URL returns 403.
    """
    url = entry.get("downloadUrl") or entry["url"]
    r = requests.get(url, headers={"authorization": f"Bearer {_token()}"}, timeout=180)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return len(r.content)
