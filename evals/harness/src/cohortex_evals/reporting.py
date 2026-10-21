"""Run reports as JSON and Markdown (FR-EVAL-7 basics).

Files: ``evals/reports/<timestamp>-<mode>.json`` and ``.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cohortex_evals.gate import FailingCase, GateResult, Thresholds
from cohortex_evals.metrics import Metric
from cohortex_evals.records import CaseResult, CaseRun


class RunReport(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    git_sha: str
    golden_version: str
    mode: str
    recorded: bool
    llm_model: str
    agent_api_url: str
    case_files: list[str]
    filters: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Metric]  # over every case in this run (reviewed or not)
    gate: GateResult  # over reviewed cases only
    cases: list[CaseResult]
    runs: list[CaseRun]

    @classmethod
    def load(cls, path: Path) -> RunReport:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


def report_stem(started_at: datetime, mode: str) -> str:
    return started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{mode}"


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def failing_cases_table(rows: list[FailingCase], agent_api_url: str | None = None) -> str:
    if not rows:
        return "_No failing cases._\n"
    lines = [
        "| Case | Category | Status | Failed | Investigation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        inv = row.investigation_id or "-"
        if row.investigation_id and agent_api_url:
            url = f"{agent_api_url}/v1/investigations/{row.investigation_id}"
            inv = f"[{row.investigation_id}]({url})"
        lines.append(
            f"| {row.case_id} | {row.category} | {row.status} | "
            f"{_cell(', '.join(row.failed))} | {inv} |"
        )
    return "\n".join(lines) + "\n"


def metrics_table(
    metrics: dict[str, Metric], thresholds: Thresholds | None, gate: GateResult | None
) -> str:
    checks = {c.metric: c for c in gate.checks} if gate else {}
    lines = [
        "| Metric | Name | Value | n | PR gate | Nightly target | Check |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for metric_id, metric in metrics.items():
        t = thresholds.metrics.get(metric_id) if thresholds else None
        name = t.name if t else metric.note
        gate_limit = f"{t.op} {t.gate:g}" if t and t.gate is not None else "-"
        target = f"{t.op} {t.target:g}" if t and t.target is not None else "-"
        check = checks.get(metric_id)
        verdict = "-"
        if check is not None:
            verdict = {True: "pass", False: "**FAIL**", None: check.reason or "-"}[check.passed]
        lines.append(
            f"| {metric_id} | {_cell(name)} | {_fmt(metric.value)} | {metric.denominator} | "
            f"{gate_limit} | {target} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def render_markdown(report: RunReport, thresholds: Thresholds | None) -> str:
    gate = report.gate
    out = [
        f"# Eval run {report.run_id}",
        "",
        f"- Started: {report.started_at.isoformat()}  Finished: {report.finished_at.isoformat()}",
        f"- Mode: `{report.mode}`  Recorded responses: {report.recorded}  "
        f"LLM: `{report.llm_model}`",
        f"- Golden set: `{report.golden_version}`  Git: `{report.git_sha}`",
        f"- Cases run: {len(report.cases)} (reviewed: {gate.reviewed_cases})",
        "",
        f"## Gate: **{gate.status.upper()}** ({gate.level} thresholds, reviewed cases only)",
        "",
    ]
    out += [f"- {r}" for r in gate.reasons]
    out += [f"- _{n}_" for n in gate.notes]
    if gate.metrics:
        out += [
            "",
            "### Gate metrics (reviewed cases)",
            "",
            metrics_table(gate.metrics, thresholds, gate),
        ]
    out += [
        "### Failing reviewed cases",
        "",
        failing_cases_table(gate.failing_cases, report.agent_api_url),
    ]
    out += [
        "## All cases in this run",
        "",
        "### Metrics (all cases, reviewed or not)",
        "",
        metrics_table(report.metrics, thresholds, None),
        "### Cases",
        "",
        "| Case | Category | Reviewed | Status | Passed | Failed graders | Latency s "
        "| Investigation |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report.cases:
        failed = case.failed_graders()
        if case.summary_leaks:
            failed.append(f"M4 leaks={case.summary_leaks}")
        out.append(
            f"| {case.case_id} | {case.category} | {'yes' if case.reviewed else 'no'} | "
            f"{case.status} | {'yes' if case.passed else 'no'} | "
            f"{_cell(', '.join(failed)) or '-'} | "
            f"{_fmt(case.latency_s, 1)} | {case.investigation_id or '-'} |"
        )
    return "\n".join(out) + "\n"


def write_report(
    report: RunReport, out_dir: Path, thresholds: Thresholds | None
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = report_stem(report.started_at, report.mode)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report, thresholds), encoding="utf-8")
    return json_path, md_path


def latest_report(out_dir: Path, mode: str | None = None) -> Path | None:
    pattern = f"*-{mode}.json" if mode else "*.json"
    files = sorted(out_dir.glob(pattern))
    return files[-1] if files else None
