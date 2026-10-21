"""Golden-case model and JSONL loader (FR-EVAL-1).

One case is one JSON line in ``evals/golden/v{N}/cases.jsonl``; the format is evaluation spec §2.
Fields beyond the spec example are optional and documented in ``evals/harness/README.md``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Category = Literal[
    "lookup",
    "compare",
    "trend",
    "diagnostic",
    "ssd",
    "literature",
    "out_of_scope",
    "adversarial",
]
Unit = Literal["pct", "count", "drive_days", "days", "ratio", "p_value", "raw"]
TerminalStatus = Literal["completed", "failed", "budget_exceeded", "refused"]

CATEGORIES: tuple[Category, ...] = (
    "lookup",
    "compare",
    "trend",
    "diagnostic",
    "ssd",
    "literature",
    "out_of_scope",
    "adversarial",
)
# Categories graded by numeric_primary (evaluation spec §2, graders table).
NUMERIC_CATEGORIES: frozenset[str] = frozenset({"lookup", "compare", "trend", "ssd"})
# Categories whose truth is a ranked list graded on the top entity and its value.
RANKED_CATEGORIES: frozenset[str] = frozenset({"compare", "ssd"})
# Categories whose truth comes from truth_sql over the raw layer.
SQL_CATEGORIES: frozenset[str] = NUMERIC_CATEGORIES | {"diagnostic"}
IN_SCOPE_CATEGORIES: frozenset[str] = SQL_CATEGORIES | {"literature"}

# Column every ranked (compare/ssd) truth row must carry: the top entity.
ENTITY_FIELD = "model"
# Columns every diagnostic truth row must carry.
TRUTH_SET_FIELD = "truth_set"
CANDIDATES_FIELD = "candidates"


class CaseScope(BaseModel):
    """Optional cohort scope; same shape as the agent's ``Scope`` (contracts §6)."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["backblaze", "alibaba"] | None = None
    models: list[str] = Field(default_factory=list, max_length=10)
    date_from: date | None = None
    date_to: date | None = None


class PrimaryAnswer(BaseModel):
    """Which truth column is the primary numeric answer and how close the report must be."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    unit: Unit
    abs_tol: float | None = Field(default=None, ge=0)
    rel_tol: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _needs_a_tolerance(self) -> Self:
        if self.abs_tol is None and self.rel_tol is None:
            raise ValueError("primary_answer needs abs_tol or rel_tol")
        return self


class GoldenCase(BaseModel):
    """One golden case (evaluation spec §2)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*-\d{4}$")
    category: Category
    question: str = Field(min_length=1, max_length=2000)
    scope: CaseScope | None = None
    truth_sql: str | None = None
    truth: dict[str, Any] | None = None
    truth_set: list[str] | None = None
    snapshot_id: str | None = None
    primary_answer: PrimaryAnswer | None = None
    required_entities: list[str] = Field(default_factory=list)
    must_refuse: bool
    reviewed_by: str | None = None
    notes: str = ""
    # Literature cases: human-labeled relevant passage IDs (WP-10); empty until labeled.
    relevant_passages: list[str] = Field(default_factory=list)
    # Adversarial cases: planted string that must never appear in the output.
    canary: str | None = None
    # Adversarial cases: terminal statuses that count as a safe outcome.
    accept_statuses: list[TerminalStatus] | None = None
    # Adversarial cases: fixture under evals/adversarial/ the case is paired with.
    fixture: str | None = None

    @model_validator(mode="after")
    def _category_rules(self) -> Self:
        cat = self.category
        if cat in SQL_CATEGORIES and not (self.truth_sql and self.truth_sql.strip()):
            raise ValueError(f"{cat} cases need truth_sql")
        if cat in NUMERIC_CATEGORIES and self.primary_answer is None:
            raise ValueError(f"{cat} cases need primary_answer")
        if cat == "out_of_scope" and not self.must_refuse:
            raise ValueError("out_of_scope cases must have must_refuse = true")
        if cat in IN_SCOPE_CATEGORIES and self.must_refuse:
            raise ValueError(f"{cat} cases are in scope; must_refuse must be false")
        if self.reviewed_by is not None and not self.reviewed_by.strip():
            raise ValueError("reviewed_by must be null or a reviewer name")
        return self

    @property
    def reviewed(self) -> bool:
        return self.reviewed_by is not None

    @property
    def in_scope(self) -> bool:
        return self.category in IN_SCOPE_CATEGORIES


class CaseFileError(Exception):
    """Raised when a case file has invalid lines or duplicate IDs."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _parse_lines(path: Path) -> tuple[list[GoldenCase], list[str]]:
    cases: list[GoldenCase] = []
    errors: list[str] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        where = f"{path}:{line_no}"
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: invalid JSON ({exc.msg})")
            continue
        try:
            cases.append(GoldenCase.model_validate(obj))
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '<case>'}: {e['msg']}"
                for e in exc.errors()
            )
            errors.append(f"{where}: {details}")
    return cases, errors


def load_cases(paths: Path | Iterable[Path]) -> list[GoldenCase]:
    """Load and validate one or more JSONL case files; IDs must be unique across all of them."""
    path_list = [paths] if isinstance(paths, Path) else list(paths)
    cases: list[GoldenCase] = []
    errors: list[str] = []
    for path in path_list:
        file_cases, file_errors = _parse_lines(path)
        cases.extend(file_cases)
        errors.extend(file_errors)
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate case id: {case.id}")
        seen.add(case.id)
    if errors:
        raise CaseFileError(errors)
    return cases


def dump_case(case: GoldenCase) -> str:
    return json.dumps(case.model_dump(mode="json"), ensure_ascii=False)


def write_cases(path: Path, cases: Sequence[GoldenCase]) -> None:
    """Rewrite a case file, one case per line, in the given order."""
    path.write_text("".join(dump_case(c) + "\n" for c in cases), encoding="utf-8")


def golden_version(path: Path) -> str:
    """``evals/golden/v1/cases.jsonl`` -> ``v1``; other layouts fall back to the file stem."""
    parent = path.parent.name
    return parent if parent.startswith("v") and parent[1:].isdigit() else path.stem


def case_json_schema() -> dict[str, Any]:
    schema = GoldenCase.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Cohortex golden case"
    return schema


def schema_text() -> str:
    return json.dumps(case_json_schema(), indent=2, sort_keys=True) + "\n"
