"""Postgres writes for pipeline observability.

Section 6: every pipeline job writes a pipeline_runs record. Section 12: if a job
fails, the UI must show the data is stale rather than silently serving yesterday's
numbers. Those two requirements are the same requirement -- the UI can only report
staleness if jobs actually record when they ran.

Writes are best-effort by design. The archive's durability comes from Parquet and
blob storage; a Postgres outage must degrade observability, never cost a snapshot.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from pipeline.common import config


def is_configured() -> bool:
    return bool(config.DATABASE_URL)


@contextmanager
def _conn():
    import psycopg

    with psycopg.connect(config.DATABASE_URL) as c:
        yield c


def record_run(
    job: str,
    started: datetime,
    finished: datetime | None,
    status: str,
    rows_written: int = 0,
    error: str | None = None,
    meta: dict | None = None,
) -> str | None:
    """Insert a PipelineRun row. Returns the id, or None if the DB is unreachable.

    Never raises: an observability write must not be able to fail a data job.
    """
    if not is_configured():
        return None
    if status not in ("ok", "pending", "error"):
        raise ValueError(f"invalid status {status!r}")

    run_id = str(uuid.uuid4())
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """
                insert into "PipelineRun"
                    (id, job, "startedAt", "finishedAt", status, "rowsWritten", error, meta)
                values (%s, %s, %s, %s, %s::"RunStatus", %s, %s, %s::jsonb)
                """,
                (run_id, job, started, finished, status, rows_written,
                 (error or None), json.dumps(meta or {})),
            )
        return run_id
    except Exception:
        return None


@contextmanager
def track(job: str, meta: dict | None = None):
    """Wrap a job so its outcome is recorded whether it succeeds or raises.

    Usage:
        with track("kalshi_archiver") as run:
            ...
            run["rows"] = n
    """
    started = datetime.now(timezone.utc)
    state: dict = {"rows": 0, "meta": dict(meta or {})}
    try:
        yield state
    except Exception as e:
        record_run(job, started, datetime.now(timezone.utc), "error",
                   state.get("rows", 0), repr(e)[:500], state.get("meta"))
        raise
    else:
        record_run(job, started, datetime.now(timezone.utc), "ok",
                   state.get("rows", 0), None, state.get("meta"))
