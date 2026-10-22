"""End-to-end flows: backfill a Backblaze quarter, ingest Alibaba, seed the fixture (design §4A).

Each quarter: record `ingest_run` → convert to the raw layer → load serving tables in one
transaction → reconcile → mark the run `succeeded`, or `failed` on any error or mismatch.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg

from cohortex_ingest.alibaba import convert_alibaba
from cohortex_ingest.convert import convert_quarter
from cohortex_ingest.derive_load import LoadStats, Source, load_quarter
from cohortex_ingest.download import download, hash_file, quarter_url
from cohortex_ingest.migrate import apply_v1_if_needed
from cohortex_ingest.paths import local_raw_root
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.rawlayer import connect
from cohortex_ingest.reconcile import Reconciliation, ReconciliationError, reconcile_quarter
from cohortex_ingest.runs import finish_run, record_reconciliation, set_schema_version, start_run
from cohortex_ingest.settings import Settings

log = logging.getLogger(__name__)

_QUARTER_DIR = re.compile(r"^\d{4}Q[1-4]$")


@dataclass(frozen=True)
class RunOutcome:
    run_id: uuid.UUID
    source: str
    period: str
    status: str
    load: LoadStats | None
    reconciliation: Reconciliation | None


def open_serving(settings: Settings) -> psycopg.Connection:
    """Autocommit connection; V1 is applied first when Flyway has not run (impl-notes §2)."""
    conn = psycopg.connect(settings.require_database_url(), autocommit=True)
    if apply_v1_if_needed(conn, embedding_dim=settings.embedding_dim):
        log.info("applied V1__init.sql (no flyway_schema_history found)")
    return conn


def digest_files(files: Iterable[Path], base: Path) -> tuple[int, str]:
    """Total bytes and a SHA-256 over `relative_path<TAB>file_sha256` lines, for folder sources."""
    total = 0
    lines: list[str] = []
    for path in sorted(files):
        size, sha = hash_file(path)
        total += size
        lines.append(f"{path.relative_to(base).as_posix()}\t{sha}\n")
    return total, hashlib.sha256("".join(lines).encode()).hexdigest()


def _load_and_reconcile(
    pg: psycopg.Connection, raw_uri: str, source: Source, quarter: Quarter, run_id: uuid.UUID
) -> tuple[LoadStats, Reconciliation]:
    duck = connect(raw_uri)
    try:
        stats = load_quarter(pg, duck, source, quarter)
        result = reconcile_quarter(pg, duck, source, quarter)
    finally:
        duck.close()
    record_reconciliation(pg, run_id, result)
    if not result.ok:
        raise ReconciliationError(result)
    return stats, result


def ingest_backblaze_quarter(
    pg: psycopg.Connection,
    settings: Settings,
    quarter: Quarter,
    source_path: Path,
    *,
    source_url: str,
    nbytes: int,
    sha256: str,
) -> RunOutcome:
    """Convert, load and reconcile one quarter from a ZIP or a folder of daily CSVs."""
    run_id = start_run(
        pg,
        source="backblaze",
        period=quarter.label,
        source_url=source_url,
        nbytes=nbytes,
        sha256=sha256,
    )
    try:
        conv = convert_quarter(source_path, local_raw_root(settings.raw_data_uri), quarter)
        set_schema_version(pg, run_id, conv.schema_version_label)
        stats, result = _load_and_reconcile(pg, settings.raw_data_uri, "backblaze", quarter, run_id)
    except BaseException:
        finish_run(pg, run_id, "failed")
        raise
    finish_run(pg, run_id, "succeeded")
    return RunOutcome(run_id, "backblaze", quarter.label, "succeeded", stats, result)


def backfill(
    settings: Settings,
    quarter: Quarter,
    *,
    dest: Path,
    client: httpx.Client | None = None,
    zip_path: Path | None = None,
    expected_sha256: str | None = None,
) -> RunOutcome:
    """Download (or take a local ZIP), then convert → load → reconcile one Backblaze quarter."""
    if zip_path is not None:
        nbytes, sha = hash_file(zip_path)
        url, path = zip_path.resolve().as_uri(), zip_path
    else:
        got = download(quarter_url(quarter), dest, client=client, expected_sha256=expected_sha256)
        nbytes, sha, url, path = got.bytes, got.sha256, got.url, got.path
    with open_serving(settings) as pg:
        return ingest_backblaze_quarter(
            pg, settings, quarter, path, source_url=url, nbytes=nbytes, sha256=sha
        )


def ingest_alibaba(pg: psycopg.Connection, settings: Settings, src: Path) -> list[RunOutcome]:
    """Convert the Alibaba logs, then load and reconcile each calendar quarter they cover."""
    conv = convert_alibaba(src, local_raw_root(settings.raw_data_uri))
    outcomes: list[RunOutcome] = []
    for quarter in conv.quarters():
        files = conv.files_for(quarter) + ([conv.label_file] if conv.label_file else [])
        nbytes, sha = digest_files(files, src)
        run_id = start_run(
            pg,
            source="alibaba",
            period=quarter.label,
            source_url=src.resolve().as_uri(),
            nbytes=nbytes,
            sha256=sha,
        )
        try:
            set_schema_version(pg, run_id, conv.schema_version_for(quarter))
            stats, result = _load_and_reconcile(
                pg, settings.raw_data_uri, "alibaba", quarter, run_id
            )
        except BaseException:
            finish_run(pg, run_id, "failed")
            raise
        finish_run(pg, run_id, "succeeded")
        outcomes.append(RunOutcome(run_id, "alibaba", quarter.label, "succeeded", stats, result))
    return outcomes


def fixture_quarters(fixtures: Path) -> list[tuple[Quarter, Path]]:
    root = fixtures / "backblaze"
    if not root.is_dir():
        return []
    return [
        (Quarter.parse(p.name), p)
        for p in sorted(root.iterdir())
        if p.is_dir() and _QUARTER_DIR.match(p.name)
    ]


def seed(settings: Settings, fixtures: Path) -> list[RunOutcome]:
    """Load the committed fixture end to end (FR-OPS-5). Safe to run repeatedly."""
    quarters = fixture_quarters(fixtures)
    alibaba = fixtures / "alibaba"
    if not quarters and not alibaba.is_dir():
        raise FileNotFoundError(f"no fixture quarters under {fixtures / 'backblaze'}")
    outcomes: list[RunOutcome] = []
    with open_serving(settings) as pg:
        for quarter, folder in quarters:
            files = [p for p in folder.rglob("*") if p.is_file()]
            nbytes, sha = digest_files(files, folder)
            outcomes.append(
                ingest_backblaze_quarter(
                    pg,
                    settings,
                    quarter,
                    folder,
                    source_url=folder.resolve().as_uri(),
                    nbytes=nbytes,
                    sha256=sha,
                )
            )
        if alibaba.is_dir():
            outcomes.extend(ingest_alibaba(pg, settings, alibaba))
    return outcomes


def raw_quarters(settings: Settings, source: Source = "backblaze") -> list[Quarter]:
    """Quarters present in the raw layer (Backblaze partitions or Alibaba day files)."""
    root = local_raw_root(settings.raw_data_uri)
    if source == "backblaze":
        found = {
            Quarter(int(y.name.split("=")[1]), int(q.name.split("=Q")[1]))
            for y in (root / "backblaze").glob("year=*")
            for q in y.glob("quarter=Q*")
            if any(q.glob("*.parquet"))
        }
    else:
        found = set()
        for f in (root / "alibaba" / "smart").glob("year=*/month=*/*.parquet"):
            day = f.stem
            found.add(Quarter(int(day[:4]), (int(day[4:6]) - 1) // 3 + 1))
    return sorted(found)


def load_window(
    settings: Settings, quarters: list[Quarter] | None = None, source: Source = "backblaze"
) -> list[tuple[LoadStats, Reconciliation]]:
    """Load quarters already in the raw layer. Default: the latest `COHORTEX_WINDOW_QUARTERS`
    Backblaze quarters (all Alibaba quarters)."""
    if quarters is None:
        quarters = raw_quarters(settings, source)
        if source == "backblaze":
            quarters = quarters[-settings.window_quarters :]
    out: list[tuple[LoadStats, Reconciliation]] = []
    with open_serving(settings) as pg:
        duck = connect(settings.raw_data_uri)
        for q in quarters:
            stats = load_quarter(pg, duck, source, q)
            out.append((stats, reconcile_quarter(pg, duck, source, q)))
    return out
