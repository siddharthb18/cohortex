"""``cohortex-eval`` command line: validate, truth, run, gate, report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cohortex_evals.cases import (
    CATEGORIES,
    SQL_CATEGORIES,
    CaseFileError,
    GoldenCase,
    golden_version,
    load_cases,
    schema_text,
    write_cases,
)
from cohortex_evals.gate import (
    Baseline,
    GateResult,
    Thresholds,
    baseline_from_metrics,
    evaluate_gate,
    write_baseline,
)
from cohortex_evals.graders import grade_case
from cohortex_evals.metrics import compute_metrics
from cohortex_evals.records import CaseRun
from cohortex_evals.reporting import (
    RunReport,
    failing_cases_table,
    latest_report,
    metrics_table,
    render_markdown,
    write_report,
)
from cohortex_evals.runner import RunConfig, run_cases
from cohortex_evals.settings import RepoPaths, Settings, git_sha


def _print(*parts: object) -> None:
    sys.stdout.write(" ".join(str(p) for p in parts) + "\n")


def _err(*parts: object) -> None:
    sys.stderr.write(" ".join(str(p) for p in parts) + "\n")


def _default_case_files(paths: RepoPaths) -> list[Path]:
    files = [paths.golden_v1]
    if paths.adversarial_cases.is_file():
        files.append(paths.adversarial_cases)
    return files


def _load(files: Sequence[Path]) -> list[GoldenCase] | None:
    try:
        return load_cases(files)
    except CaseFileError as exc:
        for line in exc.errors:
            _err(line)
        _err(f"{len(exc.errors)} problem(s) in case files")
        return None


# --------------------------------------------------------------------------- validate
def cmd_validate(args: argparse.Namespace, paths: RepoPaths) -> int:
    files = args.cases or _default_case_files(paths)
    cases = _load(files)
    if cases is None:
        return 1
    by_cat = Counter(c.category for c in cases)
    reviewed = sum(1 for c in cases if c.reviewed)
    missing_truth = [c.id for c in cases if c.category in SQL_CATEGORIES and c.truth is None]
    _print(f"{len(cases)} cases valid in {', '.join(str(f) for f in files)}")
    for cat in CATEGORIES:
        if by_cat[cat]:
            _print(f"  {cat:<13} {by_cat[cat]}")
    _print(f"reviewed: {reviewed}/{len(cases)}; truth missing: {len(missing_truth)}")
    if args.write_schema:
        paths.case_schema.write_text(schema_text(), encoding="utf-8")
        _print(f"wrote {paths.case_schema}")
    elif not paths.case_schema.is_file() or paths.case_schema.read_text("utf-8") != schema_text():
        _err(f"{paths.case_schema} is stale; run `cohortex-eval validate --write-schema`")
        return 1
    return 0


# --------------------------------------------------------------------------- truth
def cmd_truth(args: argparse.Namespace, paths: RepoPaths) -> int:
    from cohortex_evals.truth import run_truth  # DuckDB only; never Postgres (ADR-004)

    case_file: Path = args.cases or paths.golden_v1
    cases = _load([case_file])
    if cases is None:
        return 1
    settings = Settings.from_env()
    raw = args.raw or settings.raw_data_uri
    only = set(args.only or [])
    unknown = only - {c.id for c in cases}
    if unknown:
        _err(f"unknown case id(s): {', '.join(sorted(unknown))}")
        return 1
    subset = [c for c in cases if not only or c.id in only]
    result = run_truth(subset, raw, args.views or paths.views_sql)
    _print(f"raw layer {raw} snapshot {result.snapshot_id}")
    _print(f"computed truth for {len(result.computed)} case(s)")
    computed = {c.id: c for c in result.cases if c.id in result.computed}
    if args.dry_run or only:
        for case_id in result.computed:
            _print(f"  {case_id}: {json.dumps(computed[case_id].truth)}")
    for error in result.errors:
        _err(error)
    if not args.dry_run:
        write_cases(case_file, [computed.get(c.id, c) for c in cases])
        _print(f"wrote {case_file}")
    return 1 if result.errors else 0


# --------------------------------------------------------------------------- run
def select_cases(
    cases: Sequence[GoldenCase],
    *,
    include_unreviewed: bool,
    categories: Sequence[str] | None,
    limit: int | None,
) -> list[GoldenCase]:
    selected = [c for c in cases if include_unreviewed or c.reviewed]
    if categories:
        selected = [c for c in selected if c.category in categories]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _print_gate(gate: GateResult, thresholds: Thresholds, agent_api_url: str | None) -> None:
    _print(f"Gate: {gate.status.upper()} ({gate.level}; {gate.reviewed_cases} reviewed case(s))")
    for reason in gate.reasons:
        _print(f"  - {reason}")
    for note in gate.notes:
        _print(f"  ({note})")
    if gate.metrics:
        _print()
        _print(metrics_table(gate.metrics, thresholds, gate))
    if gate.failing_cases:
        _print("Failing cases:")
        _print(failing_cases_table(gate.failing_cases, agent_api_url))


def cmd_run(args: argparse.Namespace, paths: RepoPaths) -> int:
    files: list[Path] = args.cases or _default_case_files(paths)
    all_cases = _load(files)
    if all_cases is None:
        return 1
    settings = Settings.from_env()
    agent_url = (args.agent_url or settings.agent_api_url).rstrip("/")
    if args.store and not settings.database_url:
        _err("--store needs DATABASE_URL")
        return 1
    selected = select_cases(
        all_cases,
        include_unreviewed=args.include_unreviewed,
        categories=args.category,
        limit=args.limit,
    )
    no_truth = [c.id for c in selected if c.category in SQL_CATEGORIES and c.truth is None]
    if no_truth:
        _err(f"warning: no truth yet for {len(no_truth)} case(s) (run `cohortex-eval truth`)")
    config = RunConfig(
        mode=args.mode,
        concurrency=args.concurrency,
        case_timeout_s=args.timeout,
        poll_interval_s=args.poll_interval,
        send_scope=not args.no_scope,
    )
    thresholds = Thresholds.load(args.thresholds or paths.thresholds)
    version = golden_version(files[0])
    _print(f"running {len(selected)} case(s) against {agent_url} in {args.mode} mode")

    def progress(run: CaseRun) -> None:
        _print(f"  {run.case_id}: {run.status} ({(run.latency_s or 0):.1f} s)")

    started = datetime.now(UTC)
    runs = asyncio.run(run_cases(selected, agent_url, config, on_done=progress)) if selected else []
    finished = datetime.now(UTC)
    results = [grade_case(case, run) for case, run in zip(selected, runs, strict=True)]
    baseline = Baseline.load(args.baseline or paths.baseline_v1)
    gate = evaluate_gate(results, thresholds, baseline, version)
    models = sorted({r.llm_model for r in runs if r.llm_model})
    report = RunReport(
        run_id=str(uuid.uuid4()),
        started_at=started,
        finished_at=finished,
        git_sha=git_sha(paths.root),
        golden_version=version,
        mode=args.mode,
        recorded=args.recorded,
        llm_model=",".join(models) or "unknown",
        agent_api_url=agent_url,
        case_files=[str(f) for f in files],
        filters={
            "limit": args.limit,
            "category": args.category,
            "include_unreviewed": args.include_unreviewed,
        },
        config={
            "concurrency": config.concurrency,
            "case_timeout_s": config.case_timeout_s,
            "send_scope": config.send_scope,
        },
        metrics=compute_metrics(results),
        gate=gate,
        cases=results,
        runs=runs,
    )
    json_path, md_path = write_report(report, args.out or paths.reports_dir, thresholds)
    _print(f"wrote {json_path} and {md_path}")
    _print_gate(gate, thresholds, agent_url)
    if args.store and settings.database_url:
        from cohortex_evals.store import store_run

        store_run(settings.database_url, report)
        _print(f"stored eval_run {report.run_id}")
    if runs and all(r.status == "error" for r in runs):
        _err("every case errored; is agent-service reachable at", agent_url, "?")
        return 2
    return 0


# --------------------------------------------------------------------------- gate
def _resolve_run(args: argparse.Namespace, paths: RepoPaths) -> Path | None:
    if args.run:
        return Path(args.run)
    found = latest_report(args.out or paths.reports_dir, args.mode)
    if found is None:
        _err("no run report found; pass --run or run `cohortex-eval run` first")
    return found


def cmd_gate(args: argparse.Namespace, paths: RepoPaths) -> int:
    run_path = _resolve_run(args, paths)
    if run_path is None:
        return 2
    report = RunReport.load(run_path)
    thresholds = Thresholds.load(args.thresholds or paths.thresholds)
    baseline_path = args.baseline or paths.baseline_v1
    gate = evaluate_gate(
        report.cases, thresholds, Baseline.load(baseline_path), report.golden_version, args.level
    )
    _print(f"run {report.run_id} ({run_path})")
    _print_gate(gate, thresholds, report.agent_api_url)
    if args.update_baseline:
        if gate.status == "skipped":
            _err("no reviewed cases; baseline not written")
            return 1
        write_baseline(
            baseline_path,
            baseline_from_metrics(gate.metrics, thresholds, report.golden_version, report.run_id),
        )
        _print(f"wrote baseline {baseline_path}")
    return gate.exit_code


# --------------------------------------------------------------------------- report
def cmd_report(args: argparse.Namespace, paths: RepoPaths) -> int:
    run_path = _resolve_run(args, paths)
    if run_path is None:
        return 2
    report = RunReport.load(run_path)
    thresholds = Thresholds.load(args.thresholds or paths.thresholds)
    md_path = run_path.with_suffix(".md")
    md_path.write_text(render_markdown(report, thresholds), encoding="utf-8")
    _print(f"wrote {md_path}")
    if args.store:
        settings = Settings.from_env()
        if not settings.database_url:
            _err("--store needs DATABASE_URL")
            return 1
        from cohortex_evals.store import store_run

        store_run(settings.database_url, report)
        _print(f"stored eval_run {report.run_id}")
    return 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cohortex-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate case files (FR-EVAL-1) and the JSON Schema")
    p.add_argument(
        "--cases", type=Path, nargs="+", help="case files (default: golden v1 + adversarial)"
    )
    p.add_argument(
        "--write-schema", action="store_true", help="regenerate evals/golden/case.schema.json"
    )
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser(
        "truth", help="compute truth with DuckDB over RAW_DATA_URI and write it back"
    )
    p.add_argument("--cases", type=Path, help="case file (default: evals/golden/v1/cases.jsonl)")
    p.add_argument("--raw", help="raw-layer URI (default: RAW_DATA_URI)")
    p.add_argument("--views", type=Path, help="views SQL (default: contracts/rawlayer/views.sql)")
    p.add_argument("--dry-run", action="store_true", help="compute and print; do not write")
    p.add_argument("--only", nargs="+", metavar="CASE_ID", help="only these cases (prints truth)")
    p.set_defaults(func=cmd_truth)

    p = sub.add_parser("run", help="run cases against agent-service and grade them (FR-EVAL-2/3)")
    p.add_argument("--mode", choices=["single", "orchestrated"], default="single")
    p.add_argument(
        "--cases", type=Path, nargs="+", help="case files (default: golden v1 + adversarial)"
    )
    p.add_argument("--limit", type=int)
    p.add_argument("--category", nargs="+", choices=list(CATEGORIES))
    p.add_argument(
        "--include-unreviewed", action="store_true", help="also run cases not yet reviewed"
    )
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--timeout", type=float, default=240.0, help="per-case timeout in seconds")
    p.add_argument("--poll-interval", type=float, default=2.0)
    p.add_argument("--no-scope", action="store_true", help="do not send the case scope")
    p.add_argument("--agent-url", help="agent-service base URL (default: AGENT_API_URL)")
    p.add_argument(
        "--recorded", action="store_true", help="agent-service replays recorded LLM responses"
    )
    p.add_argument(
        "--store", action="store_true", help="insert eval_run/eval_case_result (DATABASE_URL)"
    )
    p.add_argument("--out", type=Path, help="report directory (default: evals/reports)")
    p.add_argument("--thresholds", type=Path)
    p.add_argument("--baseline", type=Path)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("gate", help="apply thresholds and the regression rule to a run (FR-EVAL-6)")
    p.add_argument("--run", help="run JSON (default: latest in evals/reports)")
    p.add_argument(
        "--mode", choices=["single", "orchestrated"], help="pick the latest run of this mode"
    )
    p.add_argument("--level", choices=["gate", "target"], default="gate")
    p.add_argument("--out", type=Path, help="report directory to search")
    p.add_argument("--thresholds", type=Path)
    p.add_argument("--baseline", type=Path)
    p.add_argument(
        "--update-baseline", action="store_true", help="write this run's metrics as baseline"
    )
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("report", help="re-render a run's Markdown; optionally store it in Postgres")
    p.add_argument("--run", help="run JSON (default: latest in evals/reports)")
    p.add_argument("--mode", choices=["single", "orchestrated"])
    p.add_argument("--out", type=Path)
    p.add_argument("--thresholds", type=Path)
    p.add_argument("--store", action="store_true")
    p.set_defaults(func=cmd_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = RepoPaths.discover()
    code: int = args.func(args, paths)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
