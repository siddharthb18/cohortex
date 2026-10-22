"""FR-ING-2: each daily CSV becomes Parquet with lower-cased columns and a schema version;
Parquet row count equals CSV row count for every day."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import duckdb
import pytest
from cohortex_ingest.convert import (
    RowCountMismatchError,
    check_row_counts,
    convert_quarter,
    count_csv_rows,
    parquet_row_count,
)
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import schema_version
from cohortex_ingest.synthetic import SyntheticSummary, zip_quarter

Q2 = Quarter.parse("2026Q2")


def _csv_rows(path: Path) -> int:
    return len(path.read_text().splitlines()) - 1


def test_parquet_row_count_equals_csv_row_count_every_day(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, summary = synthetic_q2
    result = convert_quarter(src, tmp_path / "raw", Q2)
    assert len(result.days) == 91 == summary.days
    part = tmp_path / "raw" / "backblaze" / "year=2026" / "quarter=Q2"
    files = sorted(part.glob("*.parquet"))
    assert [f.name for f in files][:2] == ["2026-04-01.parquet", "2026-04-02.parquet"]
    assert len(files) == 91
    con = duckdb.connect()
    for day in result.days:
        csv_path = src / f"{day.day.isoformat()}.csv"
        assert day.csv_rows == _csv_rows(csv_path)
        assert parquet_row_count(con, day.parquet_path) == day.csv_rows


def test_columns_lower_cased_with_schema_version(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    mixed = tmp_path / "mixed"
    shutil.copytree(src, mixed)
    day = mixed / "2026-04-03.csv"
    text = day.read_text()
    header, rest = text.split("\n", 1)
    header = header.replace("serial_number", "Serial_Number").replace("model", "MODEL")
    day.write_text(header + "\n" + rest)
    result = convert_quarter(mixed, tmp_path / "raw", Q2)
    path = result.days[2].parquet_path.as_posix()
    con = duckdb.connect()
    names = [
        r[0]
        for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = false)", [path]
        ).fetchall()
    ]
    assert "serial_number" in names
    assert "model" in names
    assert all(c == c.lower() for c in names)
    assert names[-1] == "schema_version"
    versions = con.execute("SELECT DISTINCT schema_version FROM read_parquet(?)", [path]).fetchall()
    assert versions == [(schema_version(header),)]
    # Lower-casing makes the version identical to the other days.
    assert result.schema_versions == [schema_version(header)]


def test_zip_and_gzip_sources_convert_identically(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    zipped = zip_quarter(src, tmp_path / "data_Q2_2026.zip", Q2)
    gz_dir = tmp_path / "gz"
    gz_dir.mkdir()
    for f in src.glob("*.csv"):
        (gz_dir / (f.name + ".gz")).write_bytes(gzip.compress(f.read_bytes()))
    a = convert_quarter(zipped, tmp_path / "raw_a", Q2)
    b = convert_quarter(gz_dir, tmp_path / "raw_b", Q2)
    assert [d.csv_rows for d in a.days] == [d.csv_rows for d in b.days]
    con = duckdb.connect()
    diff = con.execute(
        "SELECT count(*) FROM (SELECT * FROM read_parquet(?) "
        "EXCEPT ALL SELECT * FROM read_parquet(?))",
        [a.days[5].parquet_path.as_posix(), b.days[5].parquet_path.as_posix()],
    ).fetchone()
    assert diff == (0,)


def test_rerun_replaces_quarter_partition(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    raw = tmp_path / "raw"
    convert_quarter(src, raw, Q2)
    stale = raw / "backblaze" / "year=2026" / "quarter=Q2" / "stale.parquet"
    stale.write_bytes(b"x")
    convert_quarter(src, raw, Q2)
    assert not stale.exists()


def test_day_outside_quarter_is_rejected(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    with pytest.raises(ValueError, match="2026-04-01"):
        convert_quarter(src, tmp_path / "raw", Quarter.parse("2026Q3"))


def test_count_csv_rows_ignores_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "2026-04-01.csv"
    f.write_text("a,b\n1,2\n3,4\n\n")
    assert count_csv_rows(f) == 2
    g = tmp_path / "2026-04-02.csv"
    g.write_text("a,b\n1,2\n3,4")
    assert count_csv_rows(g) == 2


def test_row_count_mismatch_is_an_error() -> None:
    with pytest.raises(RowCountMismatchError, match="2026-04-01"):
        check_row_counts("2026-04-01", csv_rows=10, parquet_rows=9)
