"""Raw-layer views (contracts/rawlayer/views.sql): `drive_day` always exists and matches
the CSVs."""

from __future__ import annotations

from pathlib import Path

from cohortex_ingest.convert import convert_quarter
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.rawlayer import connect, view_statements
from cohortex_ingest.synthetic import SyntheticSummary

DRIVE_DAY_COLUMNS = ["source", "day", "drive_id", "model", "capacity_bytes", "media", "failure"]


def test_statements_come_from_the_contract_file(tmp_path: Path) -> None:
    names = [name for name, _ in view_statements(str(tmp_path))]
    assert names == [
        "raw_backblaze_day",
        "raw_alibaba_day",
        "raw_alibaba_failure",
        "alibaba_failed_on",
        "drive_day",
    ]
    sql = dict(view_statements(str(tmp_path)))["raw_backblaze_day"]
    assert f"{tmp_path.resolve().as_posix()}/backblaze/*/*/*.parquet" in sql


def test_drive_day_exists_on_an_empty_raw_layer(tmp_path: Path) -> None:
    con = connect(str(tmp_path / "nothing-here"))
    cols = [r[0] for r in con.execute("DESCRIBE drive_day").fetchall()]
    assert cols == DRIVE_DAY_COLUMNS
    assert con.execute("SELECT count(*) FROM drive_day").fetchone() == (0,)
    for view in ("raw_backblaze_day", "raw_alibaba_day", "raw_alibaba_failure"):
        assert con.execute(f"SELECT count(*) FROM {view}").fetchone() == (0,)  # noqa: S608


def test_drive_day_matches_csv_truth(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, summary = synthetic_q2
    raw = tmp_path / "raw"
    convert_quarter(src, raw, Quarter.parse("2026Q2"))
    con = connect(str(raw))
    rows = con.execute(
        "SELECT model, count(*), sum(failure), min(source), min(media), count(DISTINCT drive_id) "
        "FROM drive_day GROUP BY model ORDER BY model"
    ).fetchall()
    expected = sorted(
        (m, s.drive_days, s.failures, "backblaze", "hdd", s.drives)
        for m, s in summary.models.items()
    )
    assert [tuple(r) for r in rows] == expected
    failed = dict(con.execute("SELECT drive_id, day FROM drive_day WHERE failure = 1").fetchall())
    assert failed == summary.failed
    assert con.execute("SELECT DISTINCT typeof(day) FROM drive_day").fetchall() == [("DATE",)]
