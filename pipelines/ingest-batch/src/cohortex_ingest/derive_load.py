"""Derive serving tables from the raw layer with DuckDB and bulk-load them into Postgres (FR-ING-4).

Rules (implementation-notes §3):

- `drive_model`: one row per source + model; `capacity_bytes` = most common positive value in
  the loaded period (NULL for Alibaba); media from `drive_day`.
- `drive`: first/last day seen, `failed_on` = day with `failure = 1`, `sampled` = md5 rule.
- `cohort_daily`: per model and day, `drive_count` = rows, `failures` = sum of `failure`.
- `smart_daily`: kept attributes for sampled drives on every observed day, and for failed drives
  on the 60 days up to and including `failed_on`.

Every quarter loads in one Postgres transaction that first deletes the source's `cohort_daily`
and `smart_daily` rows for the quarter's days, then re-inserts them, and upserts `drive`; running
it twice leaves every row count unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import duckdb
import psycopg
from psycopg import sql

from cohortex_ingest.quarters import Quarter, month_starts

log = logging.getLogger(__name__)

Source = Literal["backblaze", "alibaba"]

# contracts §1 "SMART attributes kept in serving tables" (changing it requires an ADR).
KEPT_ATTRS: dict[str, tuple[int, ...]] = {
    "backblaze": (5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242),
    "alibaba": (5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199),
}
FAILURE_WINDOW_DAYS = 60


@dataclass(frozen=True)
class _SmartSource:
    view: str
    drive_id: str
    day: str
    raw: str  # column name pattern for the raw value
    normalized: str


SMART_SOURCES: dict[str, _SmartSource] = {
    "backblaze": _SmartSource(
        "raw_backblaze_day",
        "CAST(serial_number AS VARCHAR)",
        "CAST(date AS DATE)",
        "smart_{a}_raw",
        "smart_{a}_normalized",
    ),
    "alibaba": _SmartSource(
        "raw_alibaba_day",
        "model || ':' || CAST(disk_id AS VARCHAR)",
        "source_file_date",
        "r_{a}",
        "n_{a}",
    ),
}


@dataclass(frozen=True)
class LoadStats:
    source: str
    start: date
    end: date
    models: int
    drives: int
    cohort_rows: int
    smart_rows: int
    drive_days: int
    failures: int


def is_sampled(drive_id: str) -> bool:
    """The fixed 1% hash sample. Same rule in every language."""
    return int(hashlib.md5(drive_id.encode()).hexdigest()[:8], 16) % 100 == 0  # noqa: S324


def sampled_sql(column: str) -> str:
    """DuckDB expression equal to :func:`is_sampled` for ``column``."""
    return f"(CAST('0x' || substr(md5({column}), 1, 8) AS UBIGINT) % 100 = 0)"


def _d(day: date) -> str:
    return f"DATE '{day.isoformat()}'"


def _copy_in(cur: psycopg.Cursor[Any], statement: sql.SQL, path: Path) -> None:
    with cur.copy(statement) as cp, path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            cp.write(chunk)


def _to_csv(duck: duckdb.DuckDBPyConnection, query: str, path: Path) -> int:
    duck.execute(f"COPY ({query}) TO '{path.as_posix()}' (FORMAT csv, HEADER false)")
    row = duck.execute(f"SELECT count(*) FROM ({query})").fetchone()  # noqa: S608
    return int(row[0]) if row else 0


def _smart_query(duck: duckdb.DuckDBPyConnection, source: Source, start: date, end: date) -> str:
    src = SMART_SOURCES[source]
    present = {r[0] for r in duck.execute(f"DESCRIBE {src.view}").fetchall()}
    cols = []
    branches = []
    for a in KEPT_ATTRS[source]:
        raw, norm = src.raw.format(a=a), src.normalized.format(a=a)
        raw_expr = f'CAST("{raw}" AS DOUBLE)' if raw in present else "CAST(NULL AS DOUBLE)"
        norm_expr = (
            f'TRY_CAST(round(CAST("{norm}" AS DOUBLE)) AS SMALLINT)'
            if norm in present
            else "CAST(NULL AS SMALLINT)"
        )
        cols.append(f"{raw_expr} AS r{a}, {norm_expr} AS n{a}")
        branches.append(
            f"SELECT drive_id, day, CAST({a} AS SMALLINT) AS attr, r{a} AS raw_value, "  # noqa: S608
            f"n{a} AS normalized FROM keep WHERE r{a} IS NOT NULL OR n{a} IS NOT NULL"
        )
    lookback = start - timedelta(days=FAILURE_WINDOW_DAYS - 1)
    lookahead = end + timedelta(days=FAILURE_WINDOW_DAYS - 1)
    return f"""
        WITH f AS (
            SELECT DISTINCT drive_id, day AS fday FROM drive_day
            WHERE source = '{source}' AND failure = 1
              AND day BETWEEN {_d(start)} AND {_d(lookahead)}
        ),
        base AS (
            SELECT {src.drive_id} AS drive_id, {src.day} AS day, {", ".join(cols)}
            FROM {src.view}
            WHERE {src.day} BETWEEN {_d(lookback)} AND {_d(end)}
        ),
        keep AS (
            SELECT b.* FROM base b
            WHERE (b.day >= {_d(start)} AND {sampled_sql("b.drive_id")})
               OR EXISTS (
                    SELECT 1 FROM f WHERE f.drive_id = b.drive_id
                    AND b.day BETWEEN f.fday - {FAILURE_WINDOW_DAYS - 1} AND f.fday)
        )
        SELECT '{source}' AS source, drive_id, day, attr, raw_value, normalized FROM (
            {" UNION ALL ".join(branches)}
        )
    """  # noqa: S608 - built from fixed attribute lists and validated column names


def load_period(
    pg: psycopg.Connection,
    duck: duckdb.DuckDBPyConnection,
    source: Source,
    start: date,
    end: date,
) -> LoadStats:
    """Load ``[start, end]`` of ``source`` from the raw layer in one Postgres transaction."""
    window = f"source = '{source}' AND day BETWEEN {_d(start)} AND {_d(end)}"
    totals = duck.execute(
        f"SELECT count(*), coalesce(sum(failure), 0) FROM drive_day WHERE {window}"  # noqa: S608
    ).fetchone()
    if not totals or not totals[0]:
        raise ValueError(f"no raw rows for {source} between {start} and {end}")
    drive_days, failures = int(totals[0]), int(totals[1])

    models = duck.execute(
        f"""
        WITH caps AS (
            SELECT model, capacity_bytes, count(*) AS n FROM drive_day
            WHERE {window} AND capacity_bytes > 0 GROUP BY ALL
        ), ranked AS (
            SELECT model, capacity_bytes,
                   row_number() OVER (PARTITION BY model ORDER BY n DESC, capacity_bytes) AS rn
            FROM caps
        )
        SELECT m.model, m.media, r.capacity_bytes
        FROM (SELECT model, min(media) AS media FROM drive_day WHERE {window} GROUP BY model) m
        LEFT JOIN ranked r ON r.model = m.model AND r.rn = 1
        ORDER BY m.model
        """  # noqa: S608
    ).fetchall()

    with tempfile.TemporaryDirectory(prefix="cohortex-load-") as tmp, pg.transaction():
        work = Path(tmp)
        cur = pg.cursor()
        model_ids: list[tuple[str, int]] = []
        for model, media, capacity in models:
            row = cur.execute(
                """
                INSERT INTO drive_model (source, model, media, capacity_bytes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source, model) DO UPDATE
                   SET media = EXCLUDED.media,
                       capacity_bytes =
                         COALESCE(EXCLUDED.capacity_bytes, drive_model.capacity_bytes)
                RETURNING id
                """,
                (source, model, media, capacity),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"drive_model upsert returned no id for {model!r}")
            model_ids.append((model, int(row[0])))
        duck.execute("CREATE OR REPLACE TEMP TABLE model_ids (model VARCHAR, model_id INTEGER)")
        duck.executemany("INSERT INTO model_ids VALUES (?, ?)", model_ids)

        # cohort_daily: replace the period's rows.
        cohort_csv = work / "cohort_daily.csv"
        cohort_rows = _to_csv(
            duck,
            f"SELECT m.model_id, d.day, count(*), sum(d.failure) FROM drive_day d "  # noqa: S608
            f"JOIN model_ids m ON m.model = d.model WHERE {window} "
            "GROUP BY ALL",
            cohort_csv,
        )
        cur.execute(
            "DELETE FROM cohort_daily c USING drive_model m "
            "WHERE c.model_id = m.id AND m.source = %s AND c.day BETWEEN %s AND %s",
            (source, start, end),
        )
        _copy_in(
            cur,
            sql.SQL(
                "COPY cohort_daily (model_id, day, drive_count, failures) FROM STDIN (FORMAT csv)"
            ),
            cohort_csv,
        )

        # drive: upsert, widening first/last seen and keeping a known failure date.
        drive_csv = work / "drive.csv"
        drives = _to_csv(
            duck,
            f"""
            SELECT '{source}', g.drive_id, m.model_id, g.first_seen, g.last_seen, g.failed_on,
                   {sampled_sql("g.drive_id")}
            FROM (
                SELECT drive_id, arg_max(model, day) AS model, min(day) AS first_seen,
                       max(day) AS last_seen, min(day) FILTER (WHERE failure = 1) AS failed_on
                FROM drive_day WHERE {window} GROUP BY drive_id
            ) g JOIN model_ids m ON m.model = g.model
            """,  # noqa: S608
            drive_csv,
        )
        cur.execute("CREATE TEMP TABLE drive_stage (LIKE drive INCLUDING DEFAULTS) ON COMMIT DROP")
        _copy_in(
            cur,
            sql.SQL(
                "COPY drive_stage (source, drive_id, model_id, first_seen, last_seen, failed_on, "
                "sampled) FROM STDIN (FORMAT csv)"
            ),
            drive_csv,
        )
        cur.execute(
            """
            INSERT INTO drive
              (source, drive_id, model_id, first_seen, last_seen, failed_on, sampled)
            SELECT source, drive_id, model_id, first_seen, last_seen, failed_on, sampled
            FROM drive_stage
            ON CONFLICT (source, drive_id) DO UPDATE SET
              model_id   = CASE WHEN EXCLUDED.last_seen >= drive.last_seen
                                THEN EXCLUDED.model_id ELSE drive.model_id END,
              first_seen = LEAST(drive.first_seen, EXCLUDED.first_seen),
              last_seen  = GREATEST(drive.last_seen, EXCLUDED.last_seen),
              failed_on  = COALESCE(EXCLUDED.failed_on, drive.failed_on),
              sampled    = EXCLUDED.sampled
            """
        )

        # smart_daily: replace the period's days; add pre-period days of drives failing in it.
        duck.execute(
            "CREATE OR REPLACE TEMP TABLE smart_rows AS " + _smart_query(duck, source, start, end)
        )
        smart_csv = work / "smart_daily.csv"
        smart_rows = _to_csv(duck, "SELECT * FROM smart_rows", smart_csv)
        month_rows = duck.execute("SELECT min(day), max(day) FROM smart_rows").fetchone()
        months = (
            month_starts(month_rows[0], month_rows[1])
            if month_rows and month_rows[0] is not None
            else []
        )
        for month in months:
            ensure_smart_partition(cur, month)
        cur.execute(
            "DELETE FROM smart_daily WHERE source = %s AND day BETWEEN %s AND %s",
            (source, start, end),
        )
        cur.execute("CREATE TEMP TABLE smart_stage (LIKE smart_daily) ON COMMIT DROP")
        _copy_in(
            cur,
            sql.SQL(
                "COPY smart_stage (source, drive_id, day, attr, raw_value, normalized) "
                "FROM STDIN (FORMAT csv)"
            ),
            smart_csv,
        )
        cur.execute("INSERT INTO smart_daily SELECT * FROM smart_stage ON CONFLICT DO NOTHING")

    stats = LoadStats(
        source, start, end, len(models), drives, cohort_rows, smart_rows, drive_days, failures
    )
    log.info("loaded %s", stats)
    return stats


def partition_name(month: date) -> str:
    return f"smart_daily_y{month.year:04d}m{month.month:02d}"


def ensure_smart_partition(cur: psycopg.Cursor[Any], month: date) -> None:
    """Create the monthly `smart_daily` partition `smart_daily_yYYYYmMM` if missing."""
    first = date(month.year, month.month, 1)
    nxt = month_starts(first, first + timedelta(days=31))[1]
    cur.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} PARTITION OF smart_daily FOR VALUES FROM ({}) TO ({})"
        ).format(sql.Identifier(partition_name(first)), sql.Literal(first), sql.Literal(nxt))
    )


def load_quarter(
    pg: psycopg.Connection,
    duck: duckdb.DuckDBPyConnection,
    source: Source,
    quarter: Quarter,
) -> LoadStats:
    return load_period(pg, duck, source, quarter.start, quarter.end)
