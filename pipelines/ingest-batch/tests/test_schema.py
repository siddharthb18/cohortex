"""FR-ING-3: fail on any unknown non-SMART column, naming it."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from cohortex_ingest.convert import convert_quarter
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import (
    MissingColumnError,
    UnknownColumnError,
    schema_version,
    validate_backblaze_columns,
)
from cohortex_ingest.synthetic import SyntheticSummary, backblaze_header


def test_known_and_smart_columns_pass() -> None:
    validate_backblaze_columns(backblaze_header())
    validate_backblaze_columns(["DATE", "Serial_Number", "model", "capacity_bytes", "failure"])


def test_unknown_column_is_named() -> None:
    with pytest.raises(UnknownColumnError, match="vendor_note") as info:
        validate_backblaze_columns([*backblaze_header(), "vendor_note"])
    assert info.value.columns == ["vendor_note"]


@pytest.mark.parametrize("bad", ["smart_x_raw", "smart_5_value", "smart_5", "smart_5_raw_2"])
def test_malformed_smart_names_are_unknown(bad: str) -> None:
    with pytest.raises(UnknownColumnError, match=bad):
        validate_backblaze_columns([*backblaze_header(), bad])


def test_missing_required_column_is_named() -> None:
    header = [c for c in backblaze_header() if c != "failure"]
    with pytest.raises(MissingColumnError, match="failure"):
        validate_backblaze_columns(header)


def test_schema_version_is_sha256_prefix_of_lowercased_header() -> None:
    line = "date,Serial_Number,model,capacity_bytes,failure"
    expected = hashlib.sha256(line.lower().encode()).hexdigest()[:12]
    assert schema_version(line + "\r\n") == expected
    assert len(expected) == 12


def test_fixture_with_extra_column_fails_naming_it(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path: Path
) -> None:
    src, _ = synthetic_q2
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    day = bad / "2026-05-10.csv"
    lines = day.read_text().splitlines()
    lines[0] += ",vendor_note"
    lines[1:] = [line + ",x" for line in lines[1:]]
    day.write_text("\n".join(lines) + "\n")
    with pytest.raises(UnknownColumnError, match="vendor_note") as info:
        convert_quarter(bad, tmp_path / "raw", Quarter.parse("2026Q2"))
    assert "2026-05-10" in str(info.value)
    # The failed run leaves no partial quarter in the raw layer.
    assert not (tmp_path / "raw" / "backblaze").exists()
