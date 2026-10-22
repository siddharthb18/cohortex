"""FR-ING-6: ingest Alibaba SSD SMART logs and failure labels into the same schemas with
`source = 'alibaba'`. Acceptance: all six models present; failures match the label file."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
import pytest
from cohortex_ingest.alibaba import convert_alibaba
from cohortex_ingest.pipeline import ingest_alibaba
from cohortex_ingest.rawlayer import connect
from cohortex_ingest.schema import UnknownColumnError
from cohortex_ingest.settings import Settings
from cohortex_ingest.synthetic import ALIBABA_MODELS, AlibabaSummary, generate_alibaba


@pytest.fixture(scope="module")
def alibaba_src(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, AlibabaSummary]:
    out = tmp_path_factory.mktemp("alibaba") / "tianchi"
    return out, generate_alibaba(out, seed=5)


def test_raw_layer_layout(alibaba_src: tuple[Path, AlibabaSummary], tmp_path: Path) -> None:
    src, summary = alibaba_src
    conv = convert_alibaba(src, tmp_path)
    assert len(conv.days) == len(summary.files) == 30
    assert [q.label for q in conv.quarters()] == ["2018Q1", "2018Q2"]
    assert (tmp_path / "alibaba/smart/year=2018/month=03/20180317.parquet").is_file()
    assert (tmp_path / "alibaba/failure_label.parquet").is_file()
    assert conv.label_rows == len(summary.labels)
    con = connect(str(tmp_path))
    rows = con.execute(
        "SELECT model, count(*) FROM drive_day WHERE source = 'alibaba' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert dict(rows) == summary.drive_days
    assert con.execute("SELECT count(*) FROM drive_day WHERE source = 'backblaze'").fetchone() == (
        0,
    )
    dates = con.execute("SELECT min(source_file_date), max(source_file_date) FROM raw_alibaba_day")
    first, last = dates.fetchone() or (None, None)
    assert (first.isoformat(), last.isoformat()) == ("2018-03-17", "2018-04-15")


def test_all_six_models_and_failures_match_labels(
    alibaba_src: tuple[Path, AlibabaSummary], settings: Settings, pg: psycopg.Connection
) -> None:
    src, summary = alibaba_src
    outcomes = ingest_alibaba(pg, settings, src)
    assert [(o.period, o.status) for o in outcomes] == [
        ("2018Q1", "succeeded"),
        ("2018Q2", "succeeded"),
    ]
    assert all(o.reconciliation is not None and o.reconciliation.ok for o in outcomes)

    models = pg.execute(
        "SELECT model, media, capacity_bytes FROM drive_model WHERE source = 'alibaba' ORDER BY 1"
    ).fetchall()
    assert [m[0] for m in models] == sorted(ALIBABA_MODELS)
    assert {(m[1], m[2]) for m in models} == {("ssd", None)}

    rows = pg.execute(
        "SELECT drive_id, failed_on FROM drive WHERE source = 'alibaba' AND failed_on IS NOT NULL"
    ).fetchall()
    failed: dict[str, date] = {r[0]: r[1] for r in rows}
    assert failed == summary.expected_failed_on
    assert len(failed) == len(summary.labels)
    for model, disk, label_day in summary.labels:
        assert failed[f"{model}:{disk}"] <= label_day
    total = pg.execute(
        "SELECT sum(c.failures) FROM cohort_daily c JOIN drive_model m ON m.id = c.model_id "
        "WHERE m.source = 'alibaba'"
    ).fetchone()
    assert total == (len(summary.labels),)


def test_drive_ids_are_model_scoped_and_smart_uses_raw_columns(
    alibaba_src: tuple[Path, AlibabaSummary], settings: Settings, pg: psycopg.Connection
) -> None:
    src, summary = alibaba_src
    ingest_alibaba(pg, settings, src)
    ids = [r[0] for r in pg.execute("SELECT drive_id FROM drive WHERE source = 'alibaba'")]
    assert all(i.split(":")[0] in ALIBABA_MODELS for i in ids)
    disk_ids = [i.split(":", 1)[1] for i in ids]
    assert len(set(disk_ids)) < len(disk_ids), "fixture should reuse disk ids across models"
    failed_id = next(iter(summary.expected_failed_on))
    attrs = pg.execute(
        "SELECT attr, count(*) FROM smart_daily WHERE drive_id = %s GROUP BY attr ORDER BY attr",
        (failed_id,),
    ).fetchall()
    assert [a for a, _ in attrs] == [5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199]
    poh = pg.execute(
        "SELECT raw_value FROM smart_daily WHERE drive_id = %s AND attr = 9 ORDER BY day",
        (failed_id,),
    ).fetchall()
    assert poh[-1][0] > poh[0][0]


def test_second_ingest_leaves_counts_unchanged(
    alibaba_src: tuple[Path, AlibabaSummary], settings: Settings, pg: psycopg.Connection
) -> None:
    src, _ = alibaba_src
    ingest_alibaba(pg, settings, src)
    query = (
        "SELECT (SELECT count(*) FROM drive), (SELECT count(*) FROM cohort_daily), "
        "(SELECT count(*) FROM smart_daily), (SELECT count(*) FROM drive_model)"
    )
    first = pg.execute(query).fetchone()
    ingest_alibaba(pg, settings, src)
    assert pg.execute(query).fetchone() == first


def test_unknown_alibaba_column_is_named(tmp_path: Path) -> None:
    src = tmp_path / "src"
    generate_alibaba(src, seed=1, n_days=2, drives_per_model=2)
    day = src / "20180317.csv"
    header, *rest = day.read_text().splitlines()
    day.write_text("\n".join([header + ",vendor", *(r + ",x" for r in rest)]) + "\n")
    with pytest.raises(UnknownColumnError, match="vendor"):
        convert_alibaba(src, tmp_path / "raw")
