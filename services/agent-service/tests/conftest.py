"""Shared fixtures: a fresh Postgres database per test session (implementation-notes §2).

The schema is `db/migrations/V1__init.sql` when present; until that file lands, a verbatim copy of
contracts §2 in `tests/sql/V1__init.sql` is used.
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

import mcp  # noqa: F401  # bind the SDK before the repo's top-level mcp/ dir can shadow it

sys.path.insert(0, str(Path(__file__).parent))  # makes `agent_support` importable

from agent_support import REPO_ROOT
from cohortex_agent.db import render_v1

DEFAULT_ADMIN_URL = "postgresql://cohortex@localhost:5432/cohortex"


def v1_sql_path() -> Path:
    repo_file = REPO_ROOT / "db" / "migrations" / "V1__init.sql"
    return repo_file if repo_file.is_file() else Path(__file__).parent / "sql" / "V1__init.sql"


def _with_dbname(url: str, name: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(url)
    info["dbname"] = name
    return psycopg.conninfo.make_conninfo(**{k: str(v) for k, v in info.items() if v is not None})


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    admin_url = os.environ.get("COHORTEX_TEST_DATABASE_URL", DEFAULT_ADMIN_URL)
    name = f"cohortex_test_agent_{secrets.token_hex(4)}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _with_dbname(admin_url, name)
    try:
        with psycopg.connect(url) as conn:
            conn.execute(render_v1(v1_sql_path()).encode())
            conn.commit()
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
