"""Truth runner: executes each case's ``truth_sql`` with DuckDB over the raw layer (ADR-004)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from cohortex_evals.cases import (
    CANDIDATES_FIELD,
    ENTITY_FIELD,
    RANKED_CATEGORIES,
    TRUTH_SET_FIELD,
    GoldenCase,
)
from cohortex_evals.rawlayer import open_raw_layer, snapshot_id


class TruthError(Exception):
    """A case's truth SQL failed or returned an unusable result."""


def json_safe(value: Any) -> Any:
    """Convert a DuckDB value into plain JSON (non-finite floats become null)."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return json_safe(float(value))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def compute_truth(con: duckdb.DuckDBPyConnection, case: GoldenCase) -> dict[str, Any]:
    """Run ``truth_sql``; return its one row as a JSON-safe dict, checking columns."""
    if not case.truth_sql:
        raise TruthError(f"{case.id}: no truth_sql")
    try:
        cursor = con.execute(case.truth_sql)
        rows = cursor.fetchall()
    except duckdb.Error as exc:
        raise TruthError(f"{case.id}: truth_sql failed: {exc}") from exc
    if len(rows) != 1:
        raise TruthError(f"{case.id}: truth_sql returned {len(rows)} rows, expected exactly 1")
    columns = [d[0] for d in cursor.description or []]
    truth = {col: json_safe(val) for col, val in zip(columns, rows[0], strict=True)}

    required: list[str] = []
    if case.primary_answer is not None:
        required.append(case.primary_answer.field)
    if case.category in RANKED_CATEGORIES:
        required.append(ENTITY_FIELD)
    if case.category == "diagnostic":
        required.extend([TRUTH_SET_FIELD, CANDIDATES_FIELD])
    for col in required:
        if col not in truth:
            raise TruthError(f"{case.id}: truth_sql result has no column {col!r}")
        if truth[col] is None:
            raise TruthError(
                f"{case.id}: column {col!r} is NULL or non-finite "
                "(entity missing from the raw layer, or a zero denominator?)"
            )
    if case.primary_answer is not None:
        primary = truth[case.primary_answer.field]
        if isinstance(primary, bool) or not isinstance(primary, (int, float)):
            raise TruthError(f"{case.id}: primary field {case.primary_answer.field!r} not numeric")
    if case.category == "diagnostic":
        for col in (TRUTH_SET_FIELD, CANDIDATES_FIELD):
            if not isinstance(truth[col], list):
                raise TruthError(f"{case.id}: column {col!r} must be a list of model names")
    return truth


@dataclass(frozen=True)
class TruthRun:
    cases: list[GoldenCase]
    snapshot_id: str
    computed: list[str]
    errors: list[str]


def run_truth(
    cases: list[GoldenCase],
    raw_uri: str,
    views_sql: Path,
) -> TruthRun:
    """Fill ``truth`` (and ``truth_set`` for diagnostic cases) plus ``snapshot_id``.

    Cases without ``truth_sql`` are returned unchanged; failing cases keep their old values.
    """
    con = open_raw_layer(raw_uri, views_sql)
    try:
        snap = snapshot_id(con, raw_uri)
        out: list[GoldenCase] = []
        computed: list[str] = []
        errors: list[str] = []
        for case in cases:
            if not case.truth_sql:
                out.append(case)
                continue
            try:
                truth = compute_truth(con, case)
            except TruthError as exc:
                errors.append(str(exc))
                out.append(case)
                continue
            update: dict[str, Any] = {"truth": truth, "snapshot_id": snap}
            if case.category == "diagnostic":
                update["truth_set"] = [str(m) for m in truth[TRUTH_SET_FIELD]]
            out.append(case.model_copy(update=update))
            computed.append(case.id)
        return TruthRun(cases=out, snapshot_id=snap, computed=computed, errors=errors)
    finally:
        con.close()


def explain_truth_sql(con: duckdb.DuckDBPyConnection, case: GoldenCase) -> None:
    """Parse and bind a case's truth SQL against the views without running it."""
    if case.truth_sql:
        con.execute("EXPLAIN " + case.truth_sql).fetchall()
