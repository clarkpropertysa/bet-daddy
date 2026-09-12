"""Pull the market archive out of Blob storage so a CI job can read it.

The archive is the only place price history lives, and grading reads it to find each
market's last quote before kickoff. But nothing ever downloaded it: `blob.py` could
only PUT, no workflow fetched the artifact, and the grade step was written as
`... || true`. So grading failed in CI every single day --

    IOException: No files found that match the pattern
    "data/archive/market_snapshots/**/*.parquet"

-- and said nothing. Every graded row in the Track Record came from a laptop. A step
that is allowed to fail quietly is a step that is not running.

Files already present with the same size are skipped, so a cached run re-downloads
nothing, and `--since` bounds the fetch by the date= partition once a season's archive
outgrows a CI runner (259 files, 35.7 MB at Week 2).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.common import blob, db


def fetch_archive(dest_root: Path, prefix: str = "market_snapshots/",
                  since: str | None = None) -> dict:
    got = skipped = written = 0
    for entry in blob.listing(prefix):
        pathname = entry["pathname"]
        if since and "date=" in pathname:
            stamp = pathname.split("date=", 1)[1][:10]
            if stamp < since:
                continue
        dest = dest_root / pathname[len("market_snapshots/"):] \
            if pathname.startswith("market_snapshots/") else dest_root / pathname
        if dest.exists() and dest.stat().st_size == entry.get("size"):
            skipped += 1
            continue
        written += blob.fetch(entry, dest)
        got += 1
    return {"downloaded": got, "skipped": skipped, "bytes": written}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default="data/archive/market_snapshots")
    ap.add_argument("--prefix", default="market_snapshots/")
    ap.add_argument("--since", help="only date= partitions on or after this YYYY-MM-DD")
    a = ap.parse_args()

    if not blob.is_configured():
        raise SystemExit(
            "BLOB_READ_WRITE_TOKEN not set. Grading reads the archive from Blob; "
            "without it there is nothing to grade against.")

    with db.track("fetch_archive") as run:
        got = fetch_archive(Path(a.dest), a.prefix, a.since)
        run["rows"] = got["downloaded"]
        run["meta"].update(got)
        print(f"downloaded={got['downloaded']} skipped={got['skipped']} "
              f"mb={got['bytes'] / 1e6:.1f}")


if __name__ == "__main__":
    main()
