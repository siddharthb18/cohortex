"""``cohortex-eval`` end to end: validate, truth, run -> report files -> gate exit codes."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from cohortex_evals import cli
from cohortex_evals.cases import GoldenCase, load_cases
from cohortex_evals.records import CaseRun
from cohortex_evals.reporting import RunReport
from cohortex_evals.runner import RunConfig, run_cases
from cohortex_evals.testing import claim, evidence_body, make_report, number


def _agent_handler(afr_reported: float) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(
                202, json={"id": "11111111-1111-1111-1111-111111111111", "status": "queued"}
            )
        if "/evidence/" in path:
            return httpx.Response(
                200, json=evidence_body("ev_1", {"series": [{"afr_pct": afr_reported}]})
            )
        report = make_report(
            summary=[
                claim(
                    f"ST12000NM0008 had an AFR of {afr_reported}% in Q2 2026.",
                    [number(afr_reported, "pct", "ev_1", "series[0].afr_pct")],
                )
            ]
        )
        return httpx.Response(
            200,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "completed",
                "llm_model": "gpt-oss-20b",
                "tokens_in": 10,
                "tokens_out": 5,
                "cost_usd": 0,
                "report": report,
                "markdown": "# r",
            },
        )

    return handler


@pytest.fixture
def case_file(tmp_path: Path) -> Path:
    case = {
        "id": "lookup-0001",
        "category": "lookup",
        "question": "AFR of ST12000NM0008 in Q2 2026?",
        "truth_sql": "SELECT 1.5 AS afr_pct",
        "truth": {"afr_pct": 1.5},
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "required_entities": ["ST12000NM0008", "Q2 2026"],
        "must_refuse": False,
        "reviewed_by": "test-fixture",
    }
    unreviewed = {**case, "id": "lookup-0002", "reviewed_by": None}
    path = tmp_path / "v1" / "cases.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(case) + "\n" + json.dumps(unreviewed) + "\n", encoding="utf-8")
    return path


def _patch_transport(monkeypatch: pytest.MonkeyPatch, afr: float) -> None:
    real = run_cases

    async def patched(
        cases: Sequence[GoldenCase],
        base_url: str,
        config: RunConfig,
        *,
        on_done: Callable[[CaseRun], None] | None = None,
        **_: Any,
    ) -> list[CaseRun]:
        fast = RunConfig(mode=config.mode, concurrency=config.concurrency, poll_interval_s=0.0)
        transport = httpx.MockTransport(_agent_handler(afr))
        return await real(cases, base_url, fast, transport=transport, on_done=on_done)

    monkeypatch.setattr(cli, "run_cases", patched)


def test_validate_repo_case_files() -> None:
    assert cli.main(["validate"]) == 0


def test_gate_without_a_readable_run_exits_2(tmp_path: Path) -> None:
    assert cli.main(["gate", "--out", str(tmp_path)]) == 2  # no reports at all
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")
    assert cli.main(["gate", "--run", str(broken)]) == 2
    assert cli.main(["report", "--run", str(tmp_path / "missing.json")]) == 2


def test_validate_rejects_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "cases.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    assert cli.main(["validate", "--cases", str(bad)]) == 1


def test_truth_command_writes_back(tiny_raw: Path, tmp_path: Path) -> None:
    case = {
        "id": "lookup-0001",
        "category": "lookup",
        "question": "q",
        "truth_sql": "SELECT CAST(SUM(failure) AS DOUBLE) * 36500 / COUNT(*) AS afr_pct "
        "FROM drive_day WHERE model = 'A'",
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "must_refuse": False,
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case) + "\n", encoding="utf-8")
    assert cli.main(["truth", "--cases", str(path), "--raw", str(tiny_raw), "--dry-run"]) == 0
    assert load_cases(path)[0].truth is None
    assert cli.main(["truth", "--cases", str(path), "--raw", str(tiny_raw)]) == 0
    written = load_cases(path)[0]
    assert written.truth == {"afr_pct": pytest.approx(36500 / 6)}
    assert written.snapshot_id is not None
    assert written.snapshot_id.startswith("snap_")


def test_truth_only_updates_selected_cases(
    tiny_raw: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = {
        "category": "lookup",
        "question": "q",
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "must_refuse": False,
    }
    a = {**base, "id": "lookup-0001", "truth_sql": "SELECT 1.0 AS afr_pct"}
    b = {**base, "id": "lookup-0002", "truth_sql": "SELECT 2.0 AS afr_pct"}
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8")
    raw = str(tiny_raw)
    assert cli.main(["truth", "--cases", str(path), "--raw", raw, "--only", "lookup-0002"]) == 0
    assert 'lookup-0002: {"afr_pct": 2.0}' in capsys.readouterr().out
    first, second = load_cases(path)
    assert first.truth is None
    assert second.truth == {"afr_pct": 2.0}
    assert cli.main(["truth", "--cases", str(path), "--raw", raw, "--only", "nope-0001"]) == 1


def test_run_then_gate_passes(
    case_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_transport(monkeypatch, afr=1.5)
    out = tmp_path / "reports"
    code = cli.main(
        ["run", "--cases", str(case_file), "--out", str(out), "--agent-url", "http://agent"]
    )
    assert code == 0
    json_files = list(out.glob("*-single.json"))
    md_files = list(out.glob("*-single.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1
    report = RunReport.load(json_files[0])
    assert [c.case_id for c in report.cases] == ["lookup-0001"]  # reviewed only by default
    assert report.gate.status == "passed"
    assert report.golden_version == "v1"
    assert "Gate: **PASSED**" in md_files[0].read_text("utf-8")
    capsys.readouterr()
    assert cli.main(["gate", "--out", str(out)]) == 0
    assert "Gate: PASSED" in capsys.readouterr().out
    assert cli.main(["report", "--run", str(json_files[0])]) == 0


def test_run_then_gate_fails_with_case_table(
    case_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_transport(monkeypatch, afr=2.5)  # truth is 1.5: wrong answer, but well cited
    out = tmp_path / "reports"
    assert (
        cli.main(["run", "--cases", str(case_file), "--out", str(out), "--include-unreviewed"]) == 0
    )
    report = RunReport.load(next(out.glob("*.json")))
    assert len(report.cases) == 2
    assert report.gate.reviewed_cases == 1
    capsys.readouterr()
    assert cli.main(["gate", "--out", str(out), "--mode", "single"]) == 1
    printed = capsys.readouterr().out
    assert "Gate: FAILED" in printed
    inv = "11111111-1111-1111-1111-111111111111"
    assert (
        f"| lookup-0001 | lookup | completed | numeric_primary | "
        f"[{inv}](http://localhost:8000/v1/investigations/{inv}) |"
    ) in printed
    assert "lookup-0002" not in printed.split("Failing cases:")[1]


def test_run_with_no_reviewed_cases_skips_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paths_root: Path
) -> None:
    _patch_transport(monkeypatch, afr=1.5)
    out = tmp_path / "reports"
    golden = paths_root / "evals/golden/v1/cases.jsonl"
    assert cli.main(["run", "--cases", str(golden), "--out", str(out)]) == 0
    report = RunReport.load(next(out.glob("*.json")))
    assert report.cases == []
    assert report.gate.status == "skipped"
    assert cli.main(["gate", "--run", str(next(out.glob("*.json")))]) == 0


@pytest.fixture
def paths_root(paths: Any) -> Path:
    root: Path = paths.root
    return root
