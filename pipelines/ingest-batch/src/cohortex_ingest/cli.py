"""`cohortex-ingest` command line. Each command prints a JSON summary on stdout; logs are JSON
lines on stderr. Exit codes: 0 ok, 1 run failed (schema, download, reconciliation), 2 usage or
configuration error."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cohortex_ingest.convert import RowCountMismatchError, convert_quarter
from cohortex_ingest.derive_load import LoadStats
from cohortex_ingest.download import DownloadError, download, quarter_url
from cohortex_ingest.fixture import build_fixture
from cohortex_ingest.migrate import apply_v1_if_needed
from cohortex_ingest.paths import local_raw_root
from cohortex_ingest.pipeline import (
    RunOutcome,
    backfill,
    ingest_alibaba,
    load_window,
    open_serving,
    seed,
)
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.rawlayer import connect
from cohortex_ingest.reconcile import ReconciliationError, reconcile_quarter
from cohortex_ingest.runs import latest_run_id, record_reconciliation
from cohortex_ingest.settings import ConfigError, Settings
from cohortex_ingest.synthetic import generate_alibaba, generate_backblaze_quarter, zip_quarter

log = logging.getLogger("cohortex_ingest")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": "ingest-batch",
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _stats(stats: LoadStats) -> dict[str, Any]:
    return {
        "source": stats.source,
        "start": stats.start.isoformat(),
        "end": stats.end.isoformat(),
        "models": stats.models,
        "drives": stats.drives,
        "cohort_daily_rows": stats.cohort_rows,
        "smart_daily_rows": stats.smart_rows,
        "drive_days": stats.drive_days,
        "failures": stats.failures,
    }


def _outcome(o: RunOutcome) -> dict[str, Any]:
    return {
        "run_id": str(o.run_id),
        "source": o.source,
        "period": o.period,
        "status": o.status,
        "load": _stats(o.load) if o.load else None,
        "reconciliation": o.reconciliation.model_dump(mode="json") if o.reconciliation else None,
    }


# ---------------------------------------------------------------------------------- commands


def cmd_migrate(args: argparse.Namespace, settings: Settings) -> int:
    with open_serving(settings) as pg:
        applied = apply_v1_if_needed(pg, embedding_dim=settings.embedding_dim)
    _emit({"applied": applied})
    return 0


def cmd_download(args: argparse.Namespace, settings: Settings) -> int:
    q = Quarter.parse(args.quarter)
    got = download(quarter_url(q), Path(args.dest), expected_sha256=args.sha256)
    _emit({"url": got.url, "path": str(got.path), "bytes": got.bytes, "sha256": got.sha256})
    return 0


def cmd_backfill(args: argparse.Namespace, settings: Settings) -> int:
    q = Quarter.parse(args.quarter)
    zip_path = Path(args.zip) if args.zip else None
    outcome = backfill(
        settings, q, dest=Path(args.dest), zip_path=zip_path, expected_sha256=args.sha256
    )
    _emit(_outcome(outcome))
    return 0


def cmd_convert(args: argparse.Namespace, settings: Settings) -> int:
    q = Quarter.parse(args.quarter)
    result = convert_quarter(Path(args.src), local_raw_root(settings.raw_data_uri), q)
    _emit(
        {
            "quarter": q.label,
            "days": len(result.days),
            "rows": result.rows,
            "schema_versions": result.schema_versions,
        }
    )
    return 0


def cmd_load(args: argparse.Namespace, settings: Settings) -> int:
    quarters = [Quarter.parse(q) for q in args.quarter] if args.quarter else None
    results = load_window(settings, quarters, args.source)
    _emit([{"load": _stats(s), "reconciliation": r.model_dump(mode="json")} for s, r in results])
    return 0 if all(r.ok for _, r in results) else 1


def cmd_reconcile(args: argparse.Namespace, settings: Settings) -> int:
    q = Quarter.parse(args.quarter)
    with open_serving(settings) as pg:
        duck = connect(settings.raw_data_uri)
        result = reconcile_quarter(pg, duck, args.source, q)
        run_id = latest_run_id(pg, args.source, q.label)
        if run_id is not None:
            record_reconciliation(pg, run_id, result)
    _emit(result.model_dump(mode="json"))
    return 0 if result.ok else 1


def cmd_alibaba(args: argparse.Namespace, settings: Settings) -> int:
    with open_serving(settings) as pg:
        outcomes = ingest_alibaba(pg, settings, Path(args.src))
    _emit([_outcome(o) for o in outcomes])
    return 0


def cmd_synthetic(args: argparse.Namespace, settings: Settings) -> int:
    out = Path(args.out)
    if args.source == "alibaba":
        ali = generate_alibaba(out, seed=args.seed, gz=args.gzip)
        meta: dict[str, Any] = {
            "synthetic": True,
            "source": "alibaba",
            "seed": args.seed,
            "days": len(ali.files),
            "drive_days": ali.drive_days,
            "failures": len(ali.labels),
        }
    else:
        q = Quarter.parse(args.quarter)
        bb = generate_backblaze_quarter(out, q, seed=args.seed, gz=args.gzip)
        meta = {
            "synthetic": True,
            "source": "backblaze",
            "quarter": q.label,
            "seed": args.seed,
            "days": bb.days,
            "models": {
                name: {
                    "drives": s.drives,
                    "drive_days": s.drive_days,
                    "failures": s.failures,
                    "monthly_failures": s.monthly_failures,
                }
                for name, s in bb.models.items()
            },
        }
        if args.zip:
            meta["zip"] = str(zip_quarter(out, out.parent / q.zip_name, q))
    meta["created_by"] = "cohortex-ingest synthetic"
    meta["note"] = "SYNTHETIC data in the source's file format; not real fleet telemetry"
    (out / "fixture.json").write_text(json.dumps(meta, indent=2) + "\n")
    _emit(meta)
    return 0


def cmd_seed(args: argparse.Namespace, settings: Settings) -> int:
    outcomes = seed(settings, Path(args.fixtures))
    _emit([_outcome(o) for o in outcomes])
    return 0


def cmd_build_fixture(args: argparse.Namespace, settings: Settings) -> int:
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    target = build_fixture(Path(args.zip), models, args.sample, Path(args.out))
    _emit(json.loads((target / "fixture.json").read_text()))
    return 0


# ------------------------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cohortex-ingest", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("migrate", help="apply V1__init.sql if Flyway has not run")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("download", help="download and verify a Backblaze quarter ZIP")
    s.add_argument("--quarter", required=True, help="e.g. 2026Q2")
    s.add_argument("--dest", default="data/downloads")
    s.add_argument("--sha256", help="expected SHA-256 of the ZIP (optional)")
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("backfill", help="download → convert → load → reconcile one quarter")
    s.add_argument("--quarter", required=True)
    s.add_argument("--dest", default="data/downloads")
    s.add_argument("--zip", help="use this local ZIP instead of downloading")
    s.add_argument("--sha256", help="expected SHA-256 of the download (optional)")
    s.set_defaults(func=cmd_backfill)

    s = sub.add_parser("convert", help="convert a quarter ZIP or CSV folder into the raw layer")
    s.add_argument("--quarter", required=True)
    s.add_argument("--src", required=True, help="quarter ZIP or folder of YYYY-MM-DD.csv[.gz]")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("load", help="load raw-layer quarters into Postgres and reconcile")
    s.add_argument(
        "--quarter",
        action="append",
        help="repeatable; default: latest COHORTEX_WINDOW_QUARTERS (all for alibaba)",
    )
    s.add_argument("--source", choices=["backblaze", "alibaba"], default="backblaze")
    s.set_defaults(func=cmd_load)

    s = sub.add_parser("reconcile", help="compare raw and serving counts for a quarter")
    s.add_argument("--quarter", required=True)
    s.add_argument("--source", choices=["backblaze", "alibaba"], default="backblaze")
    s.set_defaults(func=cmd_reconcile)

    s = sub.add_parser("alibaba", help="ingest Alibaba SSD SMART logs (Tianchi CSVs)")
    s.add_argument("--src", required=True)
    s.set_defaults(func=cmd_alibaba)

    s = sub.add_parser("synthetic", help="write deterministic synthetic data in source format")
    s.add_argument("--out", required=True)
    s.add_argument("--quarter", default="2026Q2")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--source", choices=["backblaze", "alibaba"], default="backblaze")
    s.add_argument("--gzip", action="store_true", help="write .csv.gz files")
    s.add_argument("--zip", action="store_true", help="also package a Backblaze-style ZIP")
    s.set_defaults(func=cmd_synthetic)

    s = sub.add_parser("seed", help="load the committed fixture end to end (idempotent)")
    s.add_argument("--fixtures", default="data/fixtures")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("build-fixture", help="subset a real quarter ZIP into a fixture")
    s.add_argument("--zip", required=True)
    s.add_argument("--models", required=True, help="comma-separated model names")
    s.add_argument("--sample", type=float, default=0.01)
    s.add_argument("--out", default="data/fixtures/backblaze")
    s.set_defaults(func=cmd_build_fixture)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        settings = Settings.from_env()
        code: int = args.func(args, settings)
        return code
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except (
        DownloadError,
        ReconciliationError,
        RowCountMismatchError,
        ValueError,  # includes SchemaError (unknown or missing columns)
        FileNotFoundError,
    ) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
