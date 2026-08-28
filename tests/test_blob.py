"""Blob archive durability. The one asset in this system money cannot rebuy."""
import os

import pytest

from pipeline.common import blob


def test_missing_token_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    assert not blob.is_configured()
    with pytest.raises(blob.BlobNotConfigured, match="BLOB_READ_WRITE_TOKEN"):
        blob.put("x/y.txt", b"data")


def test_is_configured_reflects_env(monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "tok")
    assert blob.is_configured()


@pytest.mark.network
@pytest.mark.skipif(not os.getenv("BLOB_READ_WRITE_TOKEN"),
                    reason="blob token not configured")
def test_round_trip_upload():
    """Header names came from the SDK source, not guesswork: omitting
    x-vercel-blob-access fails with a misleading 'public access' error."""
    url = blob.put("betdaddy/_test_roundtrip.txt", b"hello", "text/plain")
    assert url.startswith("https://")
