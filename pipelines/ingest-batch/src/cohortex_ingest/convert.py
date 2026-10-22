"""Daily Backblaze CSV → Parquet in the raw layer (FR-ING-2, FR-ING-3).

Layout (contracts/rawlayer/views.sql): `{raw}/backblaze/year=YYYY/quarter=Qn/YYYY-MM-DD.parquet`,
all source columns lower-cased plus `schema_version`. A quarter is written to a staging folder
and swapped in only when every day converted and its row counts matched, so a failed run never
leaves a partial quarter behind.
"""

from __future__ import annotations

import gzip
import logging
import re
import shutil
import uuid
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import IO, cast

import duckdb

from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import column_type, schema_version, validate_backblaze_columns

log = logging.getLogger(__name__)

DAY_FILE = re.compile(r"(?:^|/)(\d{4}-\d{2}-\d{2})\.csv(?:\.gz)?$")


class RowCountMismatchError(RuntimeError):
    """A Parquet file does not hold exactly the rows of its CSV (FR-ING-2)."""


@dataclass(frozen=True)
class DayResult:
    day: date
    csv_rows: int
    parquet_rows: int
    schema_version: str
    parquet_path: Path


@dataclass
class ConvertResult:
    quarter: Quarter
    days: list[DayResult] = field(default_factory=list)

    @property
    def schema_versions(self) -> list[str]:
        return sorted({d.schema_version for d in self.days})

    @property
    def schema_version_label(self) -> str | None:
        """Stored in `ingest_run.schema_version`; comma-separated if days differ."""
        return ",".join(self.schema_versions) or None

    @property
    def rows(self) -> int:
        return sum(d.csv_rows for d in self.days)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _open_binary(path: Path) -> IO[bytes]:
    if path.name.endswith(".gz"):
        return cast(IO[bytes], gzip.open(path, "rb"))
    return path.open("rb")


def read_header(path: Path) -> str:
    with _open_binary(path) as fh:
        line = fh.readline().decode("utf-8-sig")
    return line.rstrip("\r\n")


def count_csv_rows(path: Path) -> int:
    """Data rows in a CSV, counted independently of DuckDB: non-blank lines minus the header."""
    n = 0
    with _open_binary(path) as fh:
        for line in fh:
            if line.strip():
                n += 1
    return max(n - 1, 0)


def parquet_row_count(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Row count from the Parquet footer (file metadata), not from re-reading the data."""
    row = con.execute(
        "SELECT sum(num_rows) FROM parquet_file_metadata(?)", [path.as_posix()]
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def check_row_counts(label: str, *, csv_rows: int, parquet_rows: int) -> None:
    if csv_rows != parquet_rows:
        raise RowCountMismatchError(
            f"{label}: CSV has {csv_rows} rows but Parquet has {parquet_rows}"
        )


def _parse_day(text: str, where: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"bad day file name {where!r}") from exc


def iter_day_csvs(source: Path, workdir: Path) -> Iterator[tuple[date, Path]]:
    """Yield `(day, csv_path)` in day order from a quarterly ZIP or a folder of daily CSVs.

    ZIP members are extracted one at a time into ``workdir`` and deleted after use, so a full
    quarter (about 12 GB unzipped) never sits on disk at once.
    """
    if source.is_dir():
        found: dict[date, Path] = {}
        for path in sorted(source.rglob("*.csv*")):
            m = DAY_FILE.search(path.as_posix())
            if not m:
                continue
            day = _parse_day(m.group(1), str(path))
            if day in found:
                raise ValueError(f"two files for {day}: {found[day]} and {path}")
            found[day] = path
        for day in sorted(found):
            yield day, found[day]
        return
    if not zipfile.is_zipfile(source):
        raise ValueError(f"{source} is neither a folder nor a ZIP file")
    with zipfile.ZipFile(source) as zf:
        members: dict[date, zipfile.ZipInfo] = {}
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            m = DAY_FILE.search(info.filename)
            if not m:
                continue
            day = _parse_day(m.group(1), info.filename)
            if day in members:
                raise ValueError(f"two ZIP members for {day}")
            members[day] = info
        workdir.mkdir(parents=True, exist_ok=True)
        for day in sorted(members):
            info = members[day]
            target = workdir / Path(info.filename).name
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            try:
                yield day, target
            finally:
                target.unlink(missing_ok=True)


def csv_to_parquet(
    con: duckdb.DuckDBPyConnection,
    csv_path: Path,
    out_path: Path,
    columns: Sequence[str],
    types: Sequence[str],
    extra: Sequence[tuple[str, str]] = (),
) -> int:
    """Copy a CSV to Parquet with explicit column names/types; returns the Parquet row count.

    ``extra`` adds constant columns as `(name, sql_expression)` after the source columns.
    """
    spec = ", ".join(
        f"{sql_literal(c)}: {sql_literal(t)}" for c, t in zip(columns, types, strict=True)
    )
    select = ", ".join(f'"{c}"' for c in columns)
    for name, expr in extra:
        select += f', {expr} AS "{name}"'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Column names were validated against a fixed pattern; paths and values are quoted literals.
    con.execute(
        f"COPY (SELECT {select} FROM read_csv({sql_literal(csv_path.as_posix())}, "  # noqa: S608
        f"header = true, delim = ',', quote = '\"', escape = '\"', "
        f"columns = {{{spec}}})) TO {sql_literal(out_path.as_posix())} "
        f"(FORMAT parquet, COMPRESSION zstd)"
    )
    return parquet_row_count(con, out_path)


def convert_day(
    con: duckdb.DuckDBPyConnection, day: date, csv_path: Path, out_path: Path
) -> DayResult:
    header = read_header(csv_path)
    names = validate_backblaze_columns(
        header.split(","), where=f"{day.isoformat()} ({csv_path.name})"
    )
    version = schema_version(header)
    parquet_rows = csv_to_parquet(
        con,
        csv_path,
        out_path,
        names,
        [column_type(c) for c in names],
        extra=[("schema_version", sql_literal(version))],
    )
    csv_rows = count_csv_rows(csv_path)
    check_row_counts(day.isoformat(), csv_rows=csv_rows, parquet_rows=parquet_rows)
    return DayResult(day, csv_rows, parquet_rows, version, out_path)


def quarter_partition(raw_root: Path, quarter: Quarter) -> Path:
    return raw_root / "backblaze" / f"year={quarter.year}" / f"quarter=Q{quarter.q}"


def convert_quarter(source: Path, raw_root: Path, quarter: Quarter) -> ConvertResult:
    """Convert every day file of ``source`` (ZIP or folder) into the raw layer."""
    staging_root = raw_root / ".staging"
    staging = staging_root / f"backblaze-{quarter.label}-{uuid.uuid4().hex[:8]}"
    result = ConvertResult(quarter)
    con = duckdb.connect()
    try:
        for day, csv_path in iter_day_csvs(source, staging / "_csv"):
            if not quarter.contains(day):
                raise ValueError(f"{day.isoformat()} is outside {quarter.label}")
            result.days.append(
                convert_day(con, day, csv_path, staging / "out" / f"{day.isoformat()}.parquet")
            )
        if not result.days:
            raise ValueError(f"no daily CSV files found in {source}")
        final = quarter_partition(raw_root, quarter)
        if final.exists():
            shutil.rmtree(final)
        final.parent.mkdir(parents=True, exist_ok=True)
        (staging / "out").rename(final)
        result.days = [replace(d, parquet_path=final / d.parquet_path.name) for d in result.days]
        log.info(
            "converted %s: %d days, %d rows, schema %s",
            quarter.label,
            len(result.days),
            result.rows,
            result.schema_version_label,
        )
        return result
    finally:
        con.close()
        shutil.rmtree(staging, ignore_errors=True)
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
