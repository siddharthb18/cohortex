"""Shared fixtures. Integration tests use a real Postgres (implementation-notes §2): each test
session creates `cohortex_test_ingest_<random>`, applies V1 and drops it at the end."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from cohortex_ingest.migrate import apply_v1_if_needed
from cohortex_ingest.settings import Settings
from cohortex_ingest.synthetic import SyntheticModel, SyntheticSummary, generate_backblaze_quarter
from psycopg import sql
from psycopg.conninfo import make_conninfo

BASE_URL = os.environ.get(
    "COHORTEX_TEST_DATABASE_URL", "postgresql://cohortex@localhost:5432/cohortex"
)
SERVING_TABLES = ("ingest_run", "smart_daily", "cohort_daily", "drive", "drive_model")

# Small model set so the tests stay fast; one model has a clear AFR step change.
TEST_MODELS = (
    SyntheticModel("SYN-TA", 12_000_138_625_024, 40, (1, 0, 1), vendor="seagate"),
    SyntheticModel("SYN-TB", 16_000_900_661_248, 30, (0, 1, 0), vendor="hgst"),
    SyntheticModel("SYN-STEP", 14_000_519_643_136, 50, (0, 3, 3), vendor="seagate"),
)


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    name = f"cohortex_test_ingest_{secrets.token_hex(4)}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(BASE_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            apply_v1_if_needed(conn, embedding_dim=384)
        yield url
    finally:
        with psycopg.connect(BASE_URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def pg(pg_url: str) -> Iterator[psycopg.Connection]:
    """A clean serving database for each test."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("TRUNCATE " + ", ".join(SERVING_TABLES) + " RESTART IDENTITY CASCADE")
        yield conn


@pytest.fixture
def settings(pg_url: str, tmp_path: Path) -> Settings:
    return Settings(database_url=pg_url, raw_data_uri=str(tmp_path / "raw"))


@pytest.fixture(scope="session")
def synthetic_q2(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, SyntheticSummary]:
    """A small synthetic 2026Q2 in Backblaze's daily-CSV format (read-only for tests)."""
    out = tmp_path_factory.mktemp("synthetic") / "2026Q2"
    summary = generate_backblaze_quarter(out, "2026Q2", seed=11, models=TEST_MODELS)
    return out, summary


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in SERVING_TABLES:
        row = conn.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()
        assert row is not None
        out[table] = int(row[0])
    return out
