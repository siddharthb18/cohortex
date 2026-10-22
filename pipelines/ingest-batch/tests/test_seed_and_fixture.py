"""FR-OPS-5 (`make seed` loads the committed fixture end to end, idempotently) and the
`build-fixture` subset rule (3 models, ~1% of drives by the md5 rule, plus all failed drives)."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from cohortex_ingest.convert import convert_quarter
from cohortex_ingest.derive_load import is_sampled
from cohortex_ingest.fixture import build_fixture
from cohortex_ingest.paths import find_repo_file
from cohortex_ingest.pipeline import seed
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.settings import Settings
from cohortex_ingest.synthetic import SyntheticSummary, zip_quarter

FIXTURES = find_repo_file("data/fixtures/README.md").parent
Counts = Callable[[psycopg.Connection], dict[str, int]]


def test_committed_fixture_is_small_and_labelled_synthetic() -> None:
    files = [p for p in FIXTURES.rglob("*") if p.is_file()]
    assert sum(p.stat().st_size for p in files) < 3 * 1024 * 1024
    assert all(p.stat().st_size < 5 * 1024 * 1024 for p in files)
    assert "SYNTHETIC" in (FIXTURES / "README.md").read_text()
    for meta in FIXTURES.rglob("fixture.json"):
        assert json.loads(meta.read_text())["synthetic"] is True
    days = sorted((FIXTURES / "backblaze" / "2026Q2").glob("*.csv.gz"))
    assert len(days) == 91
    header = gzip.decompress(days[0].read_bytes()).decode().splitlines()[0]
    assert header.startswith("date,serial_number,model,capacity_bytes,failure,")
    assert len(list((FIXTURES / "alibaba").glob("2018*.csv"))) == 30


def test_seed_loads_fixture_end_to_end_and_is_idempotent(
    settings: Settings, pg: psycopg.Connection, counts: Counts
) -> None:
    outcomes = seed(settings, FIXTURES)
    assert [(o.source, o.period, o.status) for o in outcomes] == [
        ("backblaze", "2026Q2", "succeeded"),
        ("alibaba", "2018Q1", "succeeded"),
        ("alibaba", "2018Q2", "succeeded"),
    ]
    first = counts(pg)
    assert first["ingest_run"] == 3
    models = pg.execute("SELECT source, count(*) FROM drive_model GROUP BY 1 ORDER BY 1")
    assert models.fetchall() == [("alibaba", 6), ("backblaze", 5)]
    # The step-change model: no failures in April, several in May and June.
    monthly = pg.execute(
        "SELECT extract(month FROM c.day)::int, sum(c.failures) FROM cohort_daily c "
        "JOIN drive_model m ON m.id = c.model_id WHERE m.model = 'SYN-ST16000' "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert monthly == [(4, 0), (5, 3), (6, 4)]

    seed(settings, FIXTURES)
    second = counts(pg)
    assert second["ingest_run"] == 6  # the run log grows; serving tables do not
    assert {k: v for k, v in second.items() if k != "ingest_run"} == {
        k: v for k, v in first.items() if k != "ingest_run"
    }
    statuses = pg.execute("SELECT DISTINCT status FROM ingest_run").fetchall()
    assert statuses == [("succeeded",)]


def test_build_fixture_keeps_models_sample_and_failures(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, summary = synthetic_q2
    zipped = zip_quarter(src, tmp_path / "data_Q2_2026.zip", "2026Q2")
    models = ["SYN-TA", "SYN-STEP"]
    target = build_fixture(zipped, models, 0.01, tmp_path / "fixtures" / "backblaze")
    assert target.name == "2026Q2"
    meta = json.loads((target / "fixture.json").read_text())
    assert meta["synthetic"] is False
    assert meta["models"] == models
    serials: set[str] = set()
    for f in sorted(target.glob("*.csv.gz")):
        lines = gzip.decompress(f.read_bytes()).decode().splitlines()
        for line in lines[1:]:
            cols = line.split(",")
            assert cols[2] in models
            serials.add(cols[1])
    failed = {s for s, _ in summary.failed.items() if summary.serial_model[s] in models}
    sampled = {s for s, m in summary.serial_model.items() if m in models and is_sampled(s)}
    assert serials == failed | sampled
    assert failed
    # The subset is itself a valid quarter for the pipeline.
    result = convert_quarter(target, tmp_path / "raw", Quarter.parse("2026Q2"))
    assert len(result.days) == 91


def test_build_fixture_rejects_bad_sample(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample"):
        build_fixture(tmp_path / "x.zip", ["A"], 0.001, tmp_path)
