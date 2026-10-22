"""FR-ING-4: derive and load `drive`, `cohort_daily` and sampled `smart_daily`, one transaction
per quarter, idempotently. Acceptance: a second run leaves all row counts unchanged."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from cohortex_ingest.convert import convert_quarter
from cohortex_ingest.derive_load import KEPT_ATTRS, is_sampled, load_quarter
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.rawlayer import connect
from cohortex_ingest.synthetic import SyntheticSummary

Q1 = Quarter.parse("2026Q1")
Q2 = Quarter.parse("2026Q2")
Counts = Callable[[psycopg.Connection], dict[str, int]]


@pytest.fixture
def raw_q2(raw_q2_shared: Path) -> Path:
    return raw_q2_shared


def test_second_run_leaves_row_counts_unchanged(
    pg: psycopg.Connection, raw_q2: Path, counts: Counts
) -> None:
    duck = connect(str(raw_q2))
    load_quarter(pg, duck, "backblaze", Q2)
    first = counts(pg)
    assert all(first[t] > 0 for t in ("drive_model", "drive", "cohort_daily", "smart_daily"))
    load_quarter(pg, duck, "backblaze", Q2)
    assert counts(pg) == first


def test_serving_tables_match_truth(
    pg: psycopg.Connection, raw_q2: Path, synthetic_q2: tuple[Path, SyntheticSummary]
) -> None:
    _, summary = synthetic_q2
    stats = load_quarter(pg, connect(str(raw_q2)), "backblaze", Q2)
    assert stats.models == len(summary.models)

    models = pg.execute("SELECT model, media, capacity_bytes FROM drive_model").fetchall()
    assert {m for m, _, _ in models} == set(summary.models)
    assert {media for _, media, _ in models} == {"hdd"}
    assert dict((m, cap) for m, _, cap in models)["SYN-TB"] == 16_000_900_661_248

    cohort = pg.execute(
        "SELECT m.model, sum(c.drive_count), sum(c.failures), count(*) FROM cohort_daily c "
        "JOIN drive_model m ON m.id = c.model_id GROUP BY m.model"
    ).fetchall()
    assert {r[0]: (r[1], r[2], r[3]) for r in cohort} == {
        name: (s.drive_days, s.failures, 91) for name, s in summary.models.items()
    }

    rows = pg.execute(
        "SELECT drive_id, failed_on, sampled, first_seen, last_seen FROM drive"
    ).fetchall()
    assert len(rows) == sum(s.drives for s in summary.models.values())
    assert {r[0]: r[1] for r in rows if r[1] is not None} == summary.failed
    assert all(r[2] == is_sampled(r[0]) for r in rows)
    assert all(r[3] <= r[4] for r in rows)
    assert all(r[4] == r[1] for r in rows if r[1] is not None)  # nothing after failure


def test_smart_daily_holds_sampled_and_pre_failure_days(
    pg: psycopg.Connection, raw_q2: Path, synthetic_q2: tuple[Path, SyntheticSummary]
) -> None:
    _, summary = synthetic_q2
    duck = connect(str(raw_q2))
    load_quarter(pg, duck, "backblaze", Q2)
    smart = pg.execute(
        "SELECT drive_id, day, count(*) FROM smart_daily WHERE source = 'backblaze' "
        "GROUP BY drive_id, day"
    ).fetchall()
    kept_days = {(r[0], r[1]) for r in smart}
    expected: set[tuple[str, date]] = set()
    for drive_id, day in duck.execute("SELECT drive_id, day FROM drive_day").fetchall():
        fail = summary.failed.get(drive_id)
        in_window = fail is not None and fail - timedelta(days=59) <= day <= fail
        if is_sampled(drive_id) or in_window:
            expected.add((drive_id, day))
    assert kept_days == expected
    assert any(is_sampled(d) for d, _ in kept_days)
    # Seagate-style drives report all 13 kept attributes, HGST-style ones only 8.
    assert {r[2] for r in smart} <= {13, 8}
    attrs = {r[0] for r in pg.execute("SELECT DISTINCT attr FROM smart_daily").fetchall()}
    assert attrs == set(KEPT_ATTRS["backblaze"])
    parts = pg.execute(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
        "WHERE i.inhparent = 'smart_daily'::regclass ORDER BY 1"
    ).fetchall()
    assert [p[0] for p in parts] == [
        "smart_daily_y2026m04",
        "smart_daily_y2026m05",
        "smart_daily_y2026m06",
    ]
    poh = pg.execute(
        "SELECT raw_value, normalized FROM smart_daily WHERE attr = 9 LIMIT 1"
    ).fetchone()
    assert poh is not None
    assert poh[0] > 0
    assert poh[1] is not None


def _make_march_days(q2_src: Path, out: Path, days: int) -> set[str]:
    """End-of-2026Q1 days holding the drives of 2026-04-01, so drives span two quarters."""
    out.mkdir(parents=True)
    header, *rows = (q2_src / "2026-04-01.csv").read_text().splitlines()
    for i in range(1, days + 1):
        day = (date(2026, 4, 1) - timedelta(days=i)).isoformat()
        body = []
        for line in rows:
            cols = line.split(",")
            cols[0], cols[4] = day, "0"  # date, failure
            body.append(",".join(cols))
        (out / f"{day}.csv").write_text("\n".join([header, *body]) + "\n")
    return {line.split(",")[1] for line in rows}


def test_load_order_does_not_change_serving_tables(
    pg: psycopg.Connection,
    synthetic_q2: tuple[Path, SyntheticSummary],
    raw_q2_shared: Path,
    tmp_path: Path,
    counts: Counts,
) -> None:
    src, summary = synthetic_q2
    march_ids = _make_march_days(src, tmp_path / "march", days=20)
    raw = tmp_path / "raw"
    shutil.copytree(raw_q2_shared, raw)
    convert_quarter(tmp_path / "march", raw, Q1)
    duck = connect(str(raw))

    def snapshot() -> set[tuple[Any, ...]]:
        return set(pg.execute("SELECT * FROM smart_daily").fetchall())

    load_quarter(pg, duck, "backblaze", Q2)
    load_quarter(pg, duck, "backblaze", Q1)
    first, first_counts = snapshot(), counts(pg)
    pg.execute("TRUNCATE smart_daily, cohort_daily, drive, drive_model CASCADE")
    load_quarter(pg, duck, "backblaze", Q1)
    load_quarter(pg, duck, "backblaze", Q2)
    assert snapshot() == first
    assert counts(pg) == first_counts
    # A drive failing within 59 days of March has its March SMART rows.
    early = [s for s, d in summary.failed.items() if s in march_ids and d <= date(2026, 5, 29)]
    assert early, "fixture needs a failure within 59 days of March among March drives"
    march_days = {r[2] for r in first if r[1] == early[0] and r[2] < date(2026, 4, 1)}
    assert march_days
    first_seen = pg.execute("SELECT first_seen FROM drive WHERE drive_id = %s", (early[0],))
    assert first_seen.fetchone() == (date(2026, 3, 12),)


def test_load_without_raw_rows_fails_and_keeps_serving_data(
    pg: psycopg.Connection, raw_q2: Path, counts: Counts, tmp_path: Path
) -> None:
    raw = tmp_path / "raw"
    shutil.copytree(raw_q2, raw)
    load_quarter(pg, connect(str(raw)), "backblaze", Q2)
    before = counts(pg)
    shutil.rmtree(raw / "backblaze")
    with pytest.raises(ValueError, match="no raw rows"):
        load_quarter(pg, connect(str(raw)), "backblaze", Q2)
    assert counts(pg) == before
