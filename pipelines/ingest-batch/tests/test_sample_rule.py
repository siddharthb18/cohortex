"""The 1% hash sample: `int(md5(drive_id).hexdigest()[:8], 16) % 100 == 0`
(implementation-notes §3).
Python and the DuckDB expression used by the loader must agree exactly."""

from __future__ import annotations

import duckdb
import pytest
from cohortex_ingest.derive_load import is_sampled, sampled_sql


@pytest.mark.parametrize(
    ("drive_id", "expected"),
    [
        ("abc", False),  # md5 prefix 90015098 -> 2416005272 % 100 = 72
        ("ZLTEST00185", True),  # 2b7e03d0 -> 729678800
        ("ZLTEST00415", True),  # 722cdb80 -> 1915542400
        ("MA1:42", False),  # d6bba2b7 -> % 100 = 11
    ],
)
def test_known_vectors(drive_id: str, expected: bool) -> None:
    assert is_sampled(drive_id) is expected


def test_duckdb_expression_matches_python() -> None:
    ids = [f"ZL{i:07X}" for i in range(5000)] + [f"MB2:{i}" for i in range(2000)]
    con = duckdb.connect()
    con.execute("CREATE TABLE ids AS SELECT unnest(?::VARCHAR[]) AS drive_id", [ids])
    rows = con.execute(f"SELECT drive_id, {sampled_sql('drive_id')} FROM ids").fetchall()  # noqa: S608
    got = dict(rows)
    assert got == {i: is_sampled(i) for i in ids}
    share = sum(got.values()) / len(got)
    assert 0.005 < share < 0.015
