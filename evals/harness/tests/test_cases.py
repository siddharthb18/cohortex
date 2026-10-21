"""FR-EVAL-1: the loader validates every line and rejects duplicates; schema stays in sync."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # no inline types; stubs not pinned
import pytest
from cohortex_evals.cases import (
    CaseFileError,
    GoldenCase,
    golden_version,
    load_cases,
    schema_text,
    write_cases,
)
from cohortex_evals.settings import RepoPaths


def _lookup(case_id: str = "lookup-0001", **overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": case_id,
        "category": "lookup",
        "question": "What was the AFR of ST12000NM0008 in Q2 2026?",
        "scope": {"source": "backblaze", "date_from": "2026-04-01", "date_to": "2026-06-30"},
        "truth_sql": "SELECT 1.0 AS afr_pct",
        "truth": None,
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "required_entities": ["ST12000NM0008", "Q2 2026"],
        "must_refuse": False,
        "reviewed_by": None,
        "notes": "",
    }
    case.update(overrides)
    return case


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_file_loads(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "cases.jsonl", [json.dumps(_lookup()), "", json.dumps(_lookup("lookup-0002"))]
    )
    cases = load_cases(f)
    assert [c.id for c in cases] == ["lookup-0001", "lookup-0002"]
    assert not cases[0].reviewed


def test_spec_example_case_is_valid() -> None:
    example = _lookup(
        "lookup-0007",
        truth={"afr_pct": None},
        reviewed_by="siddharth",
        notes="Sanity check: Backblaze published 1.73% for this quarter.",
    )
    assert GoldenCase.model_validate(example).reviewed


def test_bad_line_is_rejected_with_line_number(tmp_path: Path) -> None:
    bad = _lookup("lookup-0002")
    del bad["primary_answer"]
    f = _write(tmp_path / "cases.jsonl", [json.dumps(_lookup()), json.dumps(bad), "{not json"])
    with pytest.raises(CaseFileError) as info:
        load_cases(f)
    errors = info.value.errors
    assert len(errors) == 2
    assert errors[0].startswith(f"{f}:2:")
    assert "primary_answer" in errors[0]
    assert errors[1].startswith(f"{f}:3:")
    assert "invalid JSON" in errors[1]


def test_duplicate_ids_rejected_within_and_across_files(tmp_path: Path) -> None:
    f1 = _write(tmp_path / "a.jsonl", [json.dumps(_lookup()), json.dumps(_lookup())])
    with pytest.raises(CaseFileError, match="duplicate case id: lookup-0001"):
        load_cases(f1)
    f2 = _write(tmp_path / "b.jsonl", [json.dumps(_lookup("lookup-0002"))])
    f3 = _write(tmp_path / "c.jsonl", [json.dumps(_lookup("lookup-0002"))])
    with pytest.raises(CaseFileError, match="duplicate case id: lookup-0002"):
        load_cases([f2, f3])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"extra_field": 1}, "extra_field"),
        ({"category": "gossip"}, "category"),
        ({"truth_sql": None}, "truth_sql"),
        ({"primary_answer": {"field": "afr_pct", "unit": "pct"}}, "abs_tol or rel_tol"),
        ({"primary_answer": {"field": "afr_pct", "unit": "percent", "abs_tol": 0.1}}, "unit"),
        ({"must_refuse": True}, "must_refuse"),
        ({"reviewed_by": "  "}, "reviewed_by"),
        ({"id": "Lookup 7"}, "id"),
    ],
)
def test_rule_violations(tmp_path: Path, overrides: dict[str, Any], message: str) -> None:
    f = _write(tmp_path / "cases.jsonl", [json.dumps(_lookup(**overrides))])
    with pytest.raises(CaseFileError, match=message):
        load_cases(f)


def test_out_of_scope_must_refuse(tmp_path: Path) -> None:
    case = {
        "id": "out_of_scope-0001",
        "category": "out_of_scope",
        "question": "Buy?",
        "must_refuse": False,
    }
    f = _write(tmp_path / "cases.jsonl", [json.dumps(case)])
    with pytest.raises(CaseFileError, match="must_refuse"):
        load_cases(f)


def test_write_round_trip(tmp_path: Path) -> None:
    f = _write(tmp_path / "cases.jsonl", [json.dumps(_lookup())])
    cases = load_cases(f)
    write_cases(f, [cases[0].model_copy(update={"truth": {"afr_pct": 1.5}})])
    assert load_cases(f)[0].truth == {"afr_pct": 1.5}


def test_golden_version_from_path() -> None:
    assert golden_version(Path("evals/golden/v1/cases.jsonl")) == "v1"
    assert golden_version(Path("evals/adversarial/cases.jsonl")) == "cases"


def test_schema_file_is_current(paths: RepoPaths) -> None:
    assert paths.case_schema.read_text("utf-8") == schema_text(), (
        "regenerate with `cohortex-eval validate --write-schema`"
    )


def test_repo_case_files_validate(paths: RepoPaths) -> None:
    schema = json.loads(paths.case_schema.read_text("utf-8"))
    files = [paths.golden_v1, paths.adversarial_cases]
    cases = load_cases(files)
    for f in files:
        for line in f.read_text("utf-8").splitlines():
            jsonschema.validate(json.loads(line), schema)
    assert len({c.id for c in cases}) == len(cases)


def test_golden_v1_draft_shape(paths: RepoPaths) -> None:
    cases = load_cases(paths.golden_v1)
    assert len(cases) == 30
    assert Counter(c.category for c in cases) == {
        "lookup": 6,
        "compare": 6,
        "trend": 5,
        "diagnostic": 4,
        "ssd": 3,
        "literature": 2,
        "out_of_scope": 2,
        "adversarial": 2,
    }
    # Golden-set reviews are human-owned: drafted cases are never marked reviewed by an agent.
    assert all(c.reviewed_by is None for c in cases)
    assert all(c.notes for c in cases)
    sql_cases = [
        c for c in cases if c.category in {"lookup", "compare", "trend", "diagnostic", "ssd"}
    ]
    assert all(c.truth_sql and "drive_day" in c.truth_sql for c in sql_cases)


def test_adversarial_suite_shape(paths: RepoPaths) -> None:
    cases = load_cases(paths.adversarial_cases)
    assert all(c.reviewed_by is None for c in cases)
    assert any(c.canary == "CANARY-7" and c.fixture for c in cases)
    for c in cases:
        if c.fixture:
            assert (paths.root / "evals/adversarial" / c.fixture).is_file()
    fixture = (paths.root / "evals/adversarial/poisoned_tool_output.json").read_text("utf-8")
    assert "CANARY-7" in fixture
