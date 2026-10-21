"""Test helpers: a synthetic raw layer in the contract layout and Report/evidence builders.

Used by this package's tests; other components may use them to fake agent-service output.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

# (serial, model, capacity_bytes, failure)
BackblazeRow = tuple[str, str, int, int]


def write_backblaze_day(raw: Path, day: date, rows: Sequence[BackblazeRow]) -> Path:
    """Write ``{raw}/backblaze/year=YYYY/quarter=Qn/YYYY-MM-DD.parquet`` (views.sql)."""
    quarter = (day.month - 1) // 3 + 1
    out = (
        raw
        / "backblaze"
        / f"year={day.year}"
        / f"quarter=Q{quarter}"
        / f"{day.isoformat()}.parquet"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE t (date DATE, serial_number VARCHAR, model VARCHAR, "
            "capacity_bytes BIGINT, failure INTEGER, datacenter VARCHAR, smart_5_raw BIGINT, "
            "smart_5_normalized INTEGER, schema_version VARCHAR)"
        )
        # Columns travel as JSON text: far faster than binding Python lists row by row.
        con.execute(
            "INSERT INTO t SELECT CAST(? AS DATE), s, m, c, f, 'phx1', 0, 100, 'abc123def456' "
            "FROM (SELECT unnest(CAST(json(?) AS VARCHAR[])) AS s, "
            "unnest(CAST(json(?) AS VARCHAR[])) AS m, unnest(CAST(json(?) AS BIGINT[])) AS c, "
            "unnest(CAST(json(?) AS INTEGER[])) AS f)",
            [day, *(json.dumps([r[i] for r in rows]) for i in range(4))],
        )
        con.execute(f"COPY t TO '{out.as_posix()}' (FORMAT parquet)")
    finally:
        con.close()
    return out


def write_alibaba_day(raw: Path, day: date, rows: Sequence[tuple[int, str]]) -> Path:
    """``{raw}/alibaba/smart/year=YYYY/month=MM/YYYYMMDD.parquet``; rows are (disk_id, model)."""
    out = (
        raw
        / "alibaba"
        / "smart"
        / f"year={day.year}"
        / f"month={day.month:02d}"
        / f"{day.strftime('%Y%m%d')}.parquet"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE t (disk_id BIGINT, ds VARCHAR, model VARCHAR, r_5 DOUBLE, n_5 DOUBLE, "
            "source_file_date DATE)"
        )
        con.execute(
            "INSERT INTO t SELECT d, ?, m, 0, 100, CAST(? AS DATE) "
            "FROM (SELECT unnest(CAST(json(?) AS BIGINT[])) AS d, "
            "unnest(CAST(json(?) AS VARCHAR[])) AS m)",
            [
                day.strftime("%Y%m%d"),
                day,
                json.dumps([r[0] for r in rows]),
                json.dumps([r[1] for r in rows]),
            ],
        )
        con.execute(f"COPY t TO '{out.as_posix()}' (FORMAT parquet)")
    finally:
        con.close()
    return out


def write_alibaba_labels(raw: Path, labels: Iterable[tuple[str, int, str]]) -> Path:
    """``{raw}/alibaba/failure_label.parquet``; labels are (model, disk_id, failure_time)."""
    out = raw / "alibaba" / "failure_label.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (model VARCHAR, disk_id BIGINT, failure_time VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?, ?, ?)", list(labels))
        con.execute(f"COPY t TO '{out.as_posix()}' (FORMAT parquet)")
    finally:
        con.close()
    return out


# --------------------------------------------------------------------------- report builders
def number(value: float, unit: str, evidence_id: str, field: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "evidence_id": evidence_id, "field": field}


def claim(
    text: str,
    numbers: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    passage_ids: list[str] | None = None,
    status: str = "supported",
) -> dict[str, Any]:
    nums = numbers or []
    evs = (
        evidence_ids if evidence_ids is not None else sorted({str(n["evidence_id"]) for n in nums})
    )
    return {
        "text": text,
        "numbers": nums,
        "evidence_ids": evs,
        "passage_ids": passage_ids or [],
        "status": status,
    }


def make_report(
    summary: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
    unverified: list[dict[str, Any]] | None = None,
    recommended_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "question": "q",
        "scope": {"source": "backblaze", "models": [], "date_from": None, "date_to": None},
        "summary": summary or [],
        "findings": findings or [],
        "hypotheses": hypotheses or [],
        "recommended_actions": recommended_actions or [],
        "limitations": [],
        "unverified": unverified or [],
        "mode": "single",
        "model_id": "gpt-oss-20b",
        "prompt_hashes": {},
    }


def evidence_body(evidence_id: str, data: Any, tool: str = "fleet.cohort_afr") -> dict[str, Any]:
    """``GET /v1/investigations/{id}/evidence/{eid}`` body wrapping a tool envelope."""
    return {
        "evidence_id": evidence_id,
        "tool": tool,
        "args": {},
        "result": {
            "evidence_id": evidence_id,
            "tool": tool,
            "args": {},
            "source": "fleet-api",
            "generated_at": "2026-10-02T16:20:11Z",
            "data": data,
            "truncated": False,
            "next_page": None,
        },
        "created_at": "2026-10-02T16:20:11Z",
    }
