"""Environment file merging.

A bare `DATABASE_URL=""` in .env.local -- which is what `vercel env pull` leaves
behind for a variable it cannot resolve -- used to shadow the real value in .env,
because load_dotenv will not override something already "set" and counts an empty
assignment as set. Nothing raised: is_configured() returned False, every database
write was skipped by design, and jobs reported success having written nothing.
"""
import importlib

import pytest

from pipeline.common import config


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    def build(base: str, local: str | None, environ: dict | None = None):
        (tmp_path / ".env").write_text(base)
        if local is not None:
            (tmp_path / ".env.local").write_text(local)
        monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
        for k in ("DATABASE_URL", "KALSHI_KEY_ID"):
            monkeypatch.delenv(k, raising=False)
        for k, v in (environ or {}).items():
            monkeypatch.setenv(k, v)
        config._load_env()
        import os
        return os.environ
    return build


def test_empty_local_value_does_not_shadow_a_real_one(env_files):
    """The actual bug. An empty assignment means 'no opinion', not 'the empty
    string'."""
    env = env_files('DATABASE_URL="postgres://real"', 'DATABASE_URL=""')
    assert env["DATABASE_URL"] == "postgres://real"


def test_local_value_still_wins_when_it_has_one(env_files):
    """The whole point of .env.local -- overriding must keep working."""
    env = env_files('DATABASE_URL="postgres://base"', 'DATABASE_URL="postgres://local"')
    assert env["DATABASE_URL"] == "postgres://local"


def test_process_environment_beats_both_files(env_files):
    """CI passes secrets this way and must not be overwritten by a checked-out file."""
    env = env_files('DATABASE_URL="postgres://base"', 'DATABASE_URL="postgres://local"',
                    environ={"DATABASE_URL": "postgres://ci"})
    assert env["DATABASE_URL"] == "postgres://ci"


def test_missing_local_file_is_not_an_error(env_files):
    env = env_files('DATABASE_URL="postgres://base"', None)
    assert env["DATABASE_URL"] == "postgres://base"


def test_keys_only_in_local_are_still_loaded(env_files):
    env = env_files('DATABASE_URL="postgres://base"', 'KALSHI_KEY_ID="abc123"')
    assert env["KALSHI_KEY_ID"] == "abc123"
    assert env["DATABASE_URL"] == "postgres://base"
