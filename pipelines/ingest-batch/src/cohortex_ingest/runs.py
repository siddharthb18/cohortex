"""`ingest_run` bookkeeping (FR-ING-1). One row per source + period per run; an append-only log.

The row is written in its own short transaction before any loading starts, so a failed run
still leaves a `failed` row with its `finished_at`.
"""

from __future__ import annotations

import uuid
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from cohortex_ingest.reconcile import Reconciliation

Status = Literal["running", "succeeded", "failed"]


def start_run(
    pg: psycopg.Connection,
    *,
    source: str,
    period: str,
    source_url: str,
    nbytes: int,
    sha256: str,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    with pg.transaction():
        pg.execute(
            "INSERT INTO ingest_run (id, source, period, source_url, bytes, sha256, started_at, "
            "status) VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp(), 'running')",
            (run_id, source, period, source_url, nbytes, sha256),
        )
    return run_id


def set_schema_version(pg: psycopg.Connection, run_id: uuid.UUID, version: str | None) -> None:
    with pg.transaction():
        pg.execute("UPDATE ingest_run SET schema_version = %s WHERE id = %s", (version, run_id))


def record_reconciliation(
    pg: psycopg.Connection, run_id: uuid.UUID, result: Reconciliation
) -> None:
    with pg.transaction():
        pg.execute(
            "UPDATE ingest_run SET reconciliation = %s WHERE id = %s",
            (Jsonb(result.model_dump(mode="json")), run_id),
        )


def finish_run(pg: psycopg.Connection, run_id: uuid.UUID, status: Status) -> None:
    with pg.transaction():
        pg.execute(
            "UPDATE ingest_run SET status = %s, finished_at = clock_timestamp() WHERE id = %s",
            (status, run_id),
        )


def latest_run_id(pg: psycopg.Connection, source: str, period: str) -> uuid.UUID | None:
    row = pg.execute(
        "SELECT id FROM ingest_run WHERE source = %s AND period = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (source, period),
    ).fetchone()
    return row[0] if row else None
