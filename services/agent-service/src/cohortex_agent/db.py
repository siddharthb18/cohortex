"""Postgres access for agent-service (psycopg 3, async). The schema is contracts §2 / V1.

The model never writes SQL (ADR-001): every statement here is fixed and parameterized.
Each operation opens a short-lived connection, which keeps the service restart-safe and simple at
portfolio scale.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

DEFAULT_EMBEDDING_DIM = 384


def utcnow() -> datetime:
    return datetime.now(UTC)


def render_v1(sql_path: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> str:
    """V1 DDL with the Flyway placeholder filled (implementation-notes §2)."""
    return sql_path.read_text(encoding="utf-8").replace("${embedding_dim}", str(embedding_dim))


async def apply_v1_if_absent(
    database_url: str, sql_path: Path, embedding_dim: int = DEFAULT_EMBEDDING_DIM
) -> bool:
    """Apply V1 in one transaction unless Flyway (or an earlier call) already created the schema."""
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        cur = await conn.execute(
            "SELECT to_regclass('public.flyway_schema_history') IS NOT NULL"
            " OR to_regclass('public.investigation') IS NOT NULL"
        )
        row = await cur.fetchone()
        if row and row[0]:
            return False
        await conn.execute(render_v1(sql_path, embedding_dim).encode())
        await conn.commit()
        return True


class Database:
    """Fixed, parameterized queries over the serving store."""

    def __init__(self, url: str) -> None:
        self.url = url

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[psycopg.AsyncConnection[DictRow]]:
        conn = await psycopg.AsyncConnection.connect(
            self.url, autocommit=True, row_factory=dict_row
        )
        try:
            yield conn
        finally:
            await conn.close()

    async def ping(self) -> bool:
        async with self._conn() as conn:
            await conn.execute("SELECT 1")
        return True

    # ------------------------------------------------------------------ investigations

    async def create_investigation(
        self,
        *,
        investigation_id: str,
        question: str,
        scope: dict[str, Any] | None,
        mode: str,
        llm_model: str,
        prompt_hashes: dict[str, str],
    ) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "INSERT INTO investigation (id, question, scope, mode, status, llm_model,"
                " prompt_hashes, started_at) VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s)",
                (
                    uuid.UUID(investigation_id),
                    question,
                    Jsonb(scope) if scope is not None else None,
                    mode,
                    llm_model,
                    Jsonb(prompt_hashes),
                    utcnow(),
                ),
            )

    async def set_status(self, investigation_id: str, status: str) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "UPDATE investigation SET status = %s WHERE id = %s",
                (status, uuid.UUID(investigation_id)),
            )

    async def finish_investigation(
        self,
        investigation_id: str,
        *,
        status: str,
        report: dict[str, Any] | None,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
    ) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "UPDATE investigation SET status = %s, report = %s, tokens_in = %s,"
                " tokens_out = %s, cost_usd = %s, finished_at = %s WHERE id = %s",
                (
                    status,
                    Jsonb(report) if report is not None else None,
                    tokens_in,
                    tokens_out,
                    cost_usd,
                    utcnow(),
                    uuid.UUID(investigation_id),
                ),
            )

    async def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT * FROM investigation WHERE id = %s", (uuid.UUID(investigation_id),)
            )
            return await cur.fetchone()

    async def list_investigations(self, limit: int) -> list[dict[str, Any]]:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT id, question, mode, status, started_at, finished_at FROM investigation"
                " ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            return list(await cur.fetchall())

    async def fail_stale(self, older_than: datetime) -> int:
        """Restart safety (NFR-REL-2): runs left `queued`/`running` past the wall budget failed."""
        async with self._conn() as conn:
            cur = await conn.execute(
                "UPDATE investigation SET status = 'failed', finished_at = %s"
                " WHERE status IN ('queued', 'running') AND started_at < %s",
                (utcnow(), older_than),
            )
            return cur.rowcount

    # ------------------------------------------------------------------ steps, evidence, claims

    async def insert_step(
        self,
        investigation_id: str,
        *,
        seq: int,
        node: str,
        kind: str,
        payload: dict[str, Any],
        started_at: datetime,
        ended_at: datetime | None,
    ) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "INSERT INTO investigation_step (investigation_id, seq, node, kind, payload,"
                " started_at, ended_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid.UUID(investigation_id),
                    seq,
                    node,
                    kind,
                    Jsonb(payload),
                    started_at,
                    ended_at,
                ),
            )

    async def list_steps(self, investigation_id: str) -> list[dict[str, Any]]:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT seq, node, kind, payload, started_at, ended_at FROM investigation_step"
                " WHERE investigation_id = %s ORDER BY seq",
                (uuid.UUID(investigation_id),),
            )
            return list(await cur.fetchall())

    async def insert_evidence(
        self,
        *,
        evidence_id: str,
        investigation_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        created_at: datetime,
    ) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "INSERT INTO evidence (evidence_id, investigation_id, tool_name, args, result,"
                " created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    evidence_id,
                    uuid.UUID(investigation_id),
                    tool_name,
                    Jsonb(args),
                    Jsonb(result),
                    created_at,
                ),
            )

    async def get_evidence(self, investigation_id: str, evidence_id: str) -> dict[str, Any] | None:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT evidence_id, tool_name, args, result, created_at FROM evidence"
                " WHERE investigation_id = %s AND evidence_id = %s",
                (uuid.UUID(investigation_id), evidence_id),
            )
            return await cur.fetchone()

    async def evidence_results(self, investigation_id: str) -> dict[str, dict[str, Any]]:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT evidence_id, result FROM evidence WHERE investigation_id = %s"
                " ORDER BY created_at",
                (uuid.UUID(investigation_id),),
            )
            return {row["evidence_id"]: row["result"] for row in await cur.fetchall()}

    async def count_evidence(self, investigation_id: str) -> int:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM evidence WHERE investigation_id = %s",
                (uuid.UUID(investigation_id),),
            )
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

    async def insert_claims(self, investigation_id: str, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO claim (investigation_id, section, text, numbers, evidence_ids,"
                " status, checker_notes) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        uuid.UUID(investigation_id),
                        row["section"],
                        row["text"],
                        Jsonb(row["numbers"]),
                        list(row["evidence_ids"]),
                        row["status"],
                        row.get("checker_notes"),
                    )
                    for row in rows
                ],
            )

    # ------------------------------------------------------------------ alerts, evals, spend

    async def open_alerts(self) -> list[dict[str, Any]]:
        async with self._conn() as conn:
            cur = await conn.execute(
                "SELECT a.id, m.source, m.model, a.opened_at, a.window_start, a.window_end,"
                " a.baseline_afr, a.current_afr, a.rate_ratio, a.p_value"
                " FROM alert a JOIN drive_model m ON m.id = a.model_id"
                " WHERE a.status = 'open' ORDER BY a.opened_at DESC LIMIT 100"
            )
            return list(await cur.fetchall())

    async def latest_eval(self, mode: str | None) -> dict[str, Any] | None:
        async with self._conn() as conn:
            if mode:
                cur = await conn.execute(
                    "SELECT * FROM eval_run WHERE mode = %s ORDER BY started_at DESC LIMIT 1",
                    (mode,),
                )
            else:
                cur = await conn.execute("SELECT * FROM eval_run ORDER BY started_at DESC LIMIT 1")
            return await cur.fetchone()


class PostgresSpendLedger:
    """`llm_spend` monthly ledger used by the provider (NFR-COST-2)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _month() -> date:
        today = utcnow().date()
        return today.replace(day=1)

    async def month_to_date(self) -> float:
        async with self._db._conn() as conn:
            cur = await conn.execute("SELECT usd FROM llm_spend WHERE month = %s", (self._month(),))
            row = await cur.fetchone()
            return float(row["usd"]) if row else 0.0

    async def add(self, usd: float) -> None:
        async with self._db._conn() as conn:
            await conn.execute(
                "INSERT INTO llm_spend (month, usd) VALUES (%s, %s)"
                " ON CONFLICT (month) DO UPDATE SET usd = llm_spend.usd + EXCLUDED.usd",
                (self._month(), usd),
            )
