"""The `cohortex-ingest` CLI: commands wire to the pipeline and exit codes signal failures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import psycopg
import pytest
from cohortex_ingest.cli import main
from cohortex_ingest.settings import ConfigError, Settings
from cohortex_ingest.synthetic import SyntheticSummary, zip_quarter


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    assert settings.database_url is not None
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("RAW_DATA_URI", settings.raw_data_uri)
    return settings


def test_settings_from_env() -> None:
    s = Settings.from_env({"DATABASE_URL": "postgresql://x/y", "COHORTEX_WINDOW_QUARTERS": "4"})
    assert (s.raw_data_uri, s.embedding_dim, s.window_quarters) == ("./data/raw", 384, 4)
    with pytest.raises(ConfigError):
        Settings.from_env({}).require_database_url()
    with pytest.raises(ConfigError):
        Settings.from_env({"EMBEDDING_DIM": "abc"})


def test_synthetic_command_writes_labelled_quarter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "2026Q3"
    assert (
        main(["synthetic", "--out", str(out), "--quarter", "2026Q3", "--seed", "3", "--zip"]) == 0
    )
    meta = json.loads(capsys.readouterr().out)
    assert meta["synthetic"] is True
    assert meta["days"] == 92
    assert (tmp_path / "data_Q3_2026.zip").is_file()
    assert json.loads((out / "fixture.json").read_text())["seed"] == 3


def test_backfill_from_local_zip_then_reconcile_detects_corruption(
    env: Settings,
    pg: psycopg.Connection,
    synthetic_q2: tuple[Path, SyntheticSummary],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src, _ = synthetic_q2
    ten_days = tmp_path / "ten_days"
    ten_days.mkdir()
    for f in sorted(src.glob("2026-05-*.csv"))[:10]:
        shutil.copy(f, ten_days / f.name)
    zipped = zip_quarter(ten_days, tmp_path / "data_Q2_2026.zip", "2026Q2")
    assert main(["backfill", "--quarter", "2026Q2", "--zip", str(zipped)]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["status"] == "succeeded"
    assert run["reconciliation"]["ok"] is True
    assert run["load"]["start"] == "2026-04-01"

    assert main(["reconcile", "--quarter", "2026Q2"]) == 0
    capsys.readouterr()
    pg.execute("UPDATE cohort_daily SET drive_count = drive_count + 1 WHERE day = '2026-05-01'")
    assert main(["reconcile", "--quarter", "2026Q2"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    stored = pg.execute("SELECT reconciliation FROM ingest_run").fetchone()
    assert stored is not None
    assert stored[0]["ok"] is False

    # `load` re-derives the quarter from the raw layer and repairs the serving rows.
    assert main(["load"]) == 0
    assert main(["reconcile", "--quarter", "2026Q2"]) == 0


def test_missing_database_url_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["seed", "--fixtures", str(tmp_path)]) == 2


def test_unknown_column_exits_1(
    env: Settings, synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    bad = tmp_path / "bad"
    bad.mkdir()
    day = (src / "2026-04-01.csv").read_text().splitlines()
    (bad / "2026-04-01.csv").write_text(
        "\n".join([day[0] + ",mystery", *(r + ",1" for r in day[1:])]) + "\n"
    )
    assert main(["convert", "--quarter", "2026Q2", "--src", str(bad)]) == 1
