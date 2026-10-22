"""Build a small fixture from a real Backblaze quarter ZIP (WP-01, open question 8).

Keeps the chosen models only, and within them ~`sample` of drives by the md5 rule
(`int(md5(serial)[:8], 16) % 100 < round(sample * 100)`; 0.01 is exactly the serving-layer 1%
sample) plus every drive of those models that failed in the quarter. Output mirrors the ZIP:
`<out>/<YYYYQn>/YYYY-MM-DD.csv.gz`, values and header kept as published, plus `fixture.json`.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from cohortex_ingest.convert import iter_day_csvs, read_header, sql_literal
from cohortex_ingest.download import hash_file
from cohortex_ingest.duck import duck_connect
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import validate_backblaze_columns


def sample_sql(column: str, sample: float) -> str:
    k = round(sample * 100)
    if not 1 <= k <= 100:
        raise ValueError("sample must be between 0.01 and 1.0")
    return f"(CAST('0x' || substr(md5({column}), 1, 8) AS UBIGINT) % 100 < {k})"


def _read(path: Path) -> str:
    return f"read_csv({sql_literal(path.as_posix())}, header = true, all_varchar = true)"


def build_fixture(zip_path: Path, models: Sequence[str], sample: float, out: Path) -> Path:
    if not models:
        raise ValueError("at least one model is required")
    model_list = ", ".join(sql_literal(m) for m in models)
    keep_sample = sample_sql("CAST(serial_number AS VARCHAR)", sample)
    con = duck_connect()
    work = out / ".build-fixture-tmp"
    try:
        # One pass over the ZIP: keep the chosen models' rows (as text) in small staged Parquet
        # files and collect their failed serials; the sample is applied from the staged files.
        quarters: set[Quarter] = set()
        failed: set[str] = set()
        staged: dict[date, Path] = {}
        stage = work / "stage"
        stage.mkdir(parents=True, exist_ok=True)
        for day, path in iter_day_csvs(zip_path, work / "csv"):
            validate_backblaze_columns(read_header(path).split(","), where=path.name)
            quarters.add(Quarter.of(day))
            staged[day] = stage / f"{day.isoformat()}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {_read(path)} WHERE model IN ({model_list})) "  # noqa: S608
                f"TO {sql_literal(staged[day].as_posix())} (FORMAT parquet)"
            )
            rows = con.execute(
                "SELECT DISTINCT serial_number FROM read_parquet(?) WHERE failure = '1'",
                [staged[day].as_posix()],
            ).fetchall()
            failed.update(r[0] for r in rows)
        if len(quarters) != 1:
            labels = ", ".join(sorted(q.label for q in quarters)) or "none"
            raise ValueError(f"{zip_path.name} must hold exactly one quarter, found: {labels}")
        quarter = quarters.pop()
        target = out / quarter.label
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        con.execute("CREATE TEMP TABLE failed_serials (serial_number VARCHAR)")
        if failed:
            con.execute("INSERT INTO failed_serials SELECT unnest(?::VARCHAR[])", [sorted(failed)])
        for day, parquet in sorted(staged.items()):
            dest = target / f"{day.isoformat()}.csv.gz"
            con.execute(
                f"COPY (SELECT * FROM read_parquet({sql_literal(parquet.as_posix())}) "  # noqa: S608
                f"WHERE {keep_sample} OR serial_number IN (SELECT serial_number FROM "
                f"failed_serials)) TO {sql_literal(dest.as_posix())} "
                "(FORMAT csv, HEADER true, COMPRESSION gzip)"
            )
        size, sha = hash_file(zip_path)
        meta = {
            "synthetic": False,
            "source": "Backblaze Drive Stats (https://www.backblaze.com/cloud-storage/resources/"
            "hard-drive-test-data); cite Backblaze; the data may not be sold",
            "zip": zip_path.name,
            "zip_bytes": size,
            "zip_sha256": sha,
            "quarter": quarter.label,
            "models": list(models),
            "sample": sample,
            "rule": "int(md5(serial_number)[:8], 16) % 100 < round(sample * 100), "
            "plus every failed drive of the chosen models",
            "failed_drives": len(failed),
            "created_by": "cohortex-ingest build-fixture",
        }
        (target / "fixture.json").write_text(json.dumps(meta, indent=2) + "\n")
        return target
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)
