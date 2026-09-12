"""The archive must actually arrive in CI, which it never did.

`blob.py` could only PUT. No workflow downloaded the artifact. The grade step ran as
`... || true`, so every CI grading run died on an empty glob and reported success.
"""
from pathlib import Path

import pytest

from pipeline.common import blob
from pipeline.ingest.fetch_archive import fetch_archive

PAGES = [
    {"blobs": [{"pathname": "market_snapshots/date=2026-09-11/a.parquet",
                "size": 3, "downloadUrl": "https://blob/a"},
               {"pathname": "market_snapshots/date=2026-09-12/b.parquet",
                "size": 3, "url": "https://blob/b"}],
     "hasMore": True, "cursor": "c1"},
    {"blobs": [{"pathname": "market_snapshots/backfill/c.parquet",
                "size": 3, "downloadUrl": "https://blob/c"}],
     "hasMore": False},
]


@pytest.fixture
def fake_blob(monkeypatch):
    seen = {"pages": 0, "fetched": []}

    def _page(prefix, cursor, limit):
        page = PAGES[0] if cursor is None else PAGES[1]
        seen["pages"] += 1
        return page

    def _fetch(entry, dest):
        seen["fetched"].append(entry["pathname"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"xxx")
        return 3

    monkeypatch.setattr(blob, "_page", _page)
    monkeypatch.setattr(blob, "fetch", _fetch)
    return seen


def test_every_page_of_the_listing_is_followed(tmp_path, fake_blob):
    got = fetch_archive(tmp_path)
    assert got["downloaded"] == 3
    assert fake_blob["pages"] == 2, "a single page would silently truncate the archive"


def test_files_land_where_the_grader_globs_for_them(tmp_path, fake_blob):
    fetch_archive(tmp_path)
    assert (tmp_path / "date=2026-09-11/a.parquet").exists()
    assert (tmp_path / "backfill/c.parquet").exists()
    assert sorted(p.name for p in tmp_path.rglob("*.parquet")) == ["a.parquet",
                                                                  "b.parquet",
                                                                  "c.parquet"]


def test_an_unchanged_file_is_not_downloaded_twice(tmp_path, fake_blob):
    fetch_archive(tmp_path)
    again = fetch_archive(tmp_path)
    assert again["downloaded"] == 0
    assert again["skipped"] == 3


def test_since_bounds_the_fetch_by_partition(tmp_path, fake_blob):
    got = fetch_archive(tmp_path, since="2026-09-12")
    # the 09-11 snapshot is skipped; backfill carries no date= and is always kept
    assert sorted(Path(p).name for p in fake_blob["fetched"]) == ["b.parquet",
                                                                 "c.parquet"]
    assert got["downloaded"] == 2
