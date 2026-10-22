"""Alibaba SSD SMART logs → raw layer (FR-ING-6).

Input (Tianchi dataset 95044): one `YYYYMMDD.csv` per sampling day with `disk_id, ds, model`
then `n_{id}` / `r_{id}` per attribute, and `ssd_failure_label.csv` with `model, disk_id,
failure_time`. Files may sit anywhere under the source folder and may be gzipped.

Output (contracts/rawlayer/views.sql):
`{raw}/alibaba/smart/year=YYYY/month=MM/YYYYMMDD.parquet` with all source columns plus
`source_file_date`, and `{raw}/alibaba/failure_label.parquet`. Day files are replaced one by one;
the label file is replaced when the source has one.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from cohortex_ingest.convert import check_row_counts, count_csv_rows, csv_to_parquet, read_header
from cohortex_ingest.duck import duck_connect
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import (
    MissingColumnError,
    SchemaError,
    UnknownColumnError,
    schema_version,
)

log = logging.getLogger(__name__)

DAY_FILE = re.compile(r"(?:^|/)(\d{8})\.csv(?:\.gz)?$")
LABEL_FILE = "ssd_failure_label.csv"
REQUIRED = ("disk_id", "ds", "model")
ATTR_COLUMN = re.compile(r"^[nr]_\d+$")
LABEL_COLUMNS = ("model", "disk_id", "failure_time")


@dataclass
class AlibabaConvert:
    days: dict[date, Path] = field(default_factory=dict)  # day -> source file
    rows: dict[date, int] = field(default_factory=dict)
    versions: dict[date, str] = field(default_factory=dict)
    label_file: Path | None = None
    label_rows: int = 0

    def quarters(self) -> list[Quarter]:
        return sorted({Quarter.of(d) for d in self.days})

    def files_for(self, quarter: Quarter) -> list[Path]:
        return [p for d, p in sorted(self.days.items()) if quarter.contains(d)]

    def schema_version_for(self, quarter: Quarter) -> str | None:
        versions = {v for d, v in self.versions.items() if quarter.contains(d)}
        return ",".join(sorted(versions)) or None


def validate_alibaba_columns(columns: Sequence[str], *, where: str = "") -> list[str]:
    lowered = [c.strip().lower() for c in columns]
    suffix = f" in {where}" if where else ""
    dupes = sorted({c for c in lowered if lowered.count(c) > 1})
    if dupes:
        raise SchemaError(f"duplicate column(s){suffix}: {', '.join(dupes)}", dupes)
    unknown = [c for c in lowered if c not in REQUIRED and not ATTR_COLUMN.match(c)]
    if unknown:
        raise UnknownColumnError(
            f"unknown Alibaba column(s){suffix}: {', '.join(unknown)}", unknown
        )
    missing = [c for c in REQUIRED if c not in lowered]
    if missing:
        raise MissingColumnError(
            f"missing required column(s){suffix}: {', '.join(missing)}", missing
        )
    return lowered


def _type(col: str) -> str:
    return "VARCHAR" if col in REQUIRED else "DOUBLE"


def find_sources(src: Path) -> tuple[dict[date, Path], Path | None]:
    days: dict[date, Path] = {}
    label: Path | None = None
    for path in sorted(src.rglob("*.csv*")):
        if path.name in (LABEL_FILE, LABEL_FILE + ".gz"):
            if label is not None:
                raise ValueError(f"two label files: {label} and {path}")
            label = path
            continue
        m = DAY_FILE.search(path.as_posix())
        if not m:
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d").date()
        if day in days:
            raise ValueError(f"two files for {day}: {days[day]} and {path}")
        days[day] = path
    return days, label


def convert_alibaba(src: Path, raw_root: Path) -> AlibabaConvert:
    days, label = find_sources(src)
    if not days:
        raise ValueError(f"no Alibaba SMART day files (YYYYMMDD.csv) under {src}")
    result = AlibabaConvert(label_file=label)
    con = duck_connect()
    tmp_tag = uuid.uuid4().hex[:8]
    try:
        for day, path in sorted(days.items()):
            header = read_header(path)
            names = validate_alibaba_columns(header.split(","), where=f"{path.name}")
            out = (
                raw_root
                / "alibaba"
                / "smart"
                / f"year={day.year:04d}"
                / f"month={day.month:02d}"
                / f"{day:%Y%m%d}.parquet"
            )
            tmp = out.with_name(f".{out.name}.{tmp_tag}")
            n = csv_to_parquet(
                con,
                path,
                tmp,
                names,
                [_type(c) for c in names],
                extra=[("source_file_date", f"DATE '{day.isoformat()}'")],
            )
            check_row_counts(path.name, csv_rows=count_csv_rows(path), parquet_rows=n)
            tmp.replace(out)
            result.days[day] = path
            result.rows[day] = n
            result.versions[day] = schema_version(header)
        if label is not None:
            header = read_header(label)
            names = [c.strip().lower() for c in header.split(",")]
            if names != list(LABEL_COLUMNS):
                raise SchemaError(
                    f"{label.name} columns must be {', '.join(LABEL_COLUMNS)}; got {header!r}",
                    names,
                )
            out = raw_root / "alibaba" / "failure_label.parquet"
            tmp = out.with_name(f".{out.name}.{tmp_tag}")
            n = csv_to_parquet(con, label, tmp, names, ["VARCHAR"] * len(names))
            check_row_counts(label.name, csv_rows=count_csv_rows(label), parquet_rows=n)
            tmp.replace(out)
            result.label_rows = n
    finally:
        con.close()
        for leftover in (raw_root / "alibaba").rglob(f".*.{tmp_tag}"):
            leftover.unlink(missing_ok=True)
    log.info(
        "converted Alibaba: %d days (%s), %d label rows",
        len(result.days),
        ", ".join(q.label for q in result.quarters()),
        result.label_rows,
    )
    return result


def files_by_quarter(conv: AlibabaConvert) -> dict[Quarter, list[Path]]:
    out: dict[Quarter, list[Path]] = defaultdict(list)
    for q in conv.quarters():
        out[q] = conv.files_for(q)
    return out
