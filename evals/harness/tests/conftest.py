"""Shared fixtures: repo paths and synthetic raw layers in the contract layout."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from cohortex_evals.settings import RepoPaths, repo_root
from cohortex_evals.testing import (
    BackblazeRow,
    write_alibaba_day,
    write_alibaba_labels,
    write_backblaze_day,
)

BACKBLAZE_MODELS = [
    "ST12000NM0008",
    "ST14000NM001G",
    "ST16000NM001G",
    "TOSHIBA MG07ACA14TA",
    "TOSHIBA MG08ACA16TEY",
    "WDC WUH721816ALE6L4",
    "HGST HUH721212ALE604",
    "ST8000NM0055",
]
ALIBABA_MODELS = ["MA1", "MA2", "MB1", "MB2", "MC1", "MC2"]
QUARTER_DAYS = {
    (2025, 3): [date(2025, 7, 1), date(2025, 9, 30)],
    (2025, 4): [date(2025, 10, 1), date(2025, 12, 31)],
    (2026, 1): [date(2026, 1, 1), date(2026, 3, 31)],
    (2026, 2): [date(2026, 4, 1), date(2026, 6, 30)],
}
CAP = 12_000_138_625_024


@pytest.fixture(scope="session")
def paths() -> RepoPaths:
    return RepoPaths(repo_root(Path(__file__).resolve()))


@pytest.fixture
def tiny_raw(tmp_path: Path) -> Path:
    """Hand-checkable raw layer.

    Backblaze 2026-01-01..02: model A has 3 drives/day and A1 fails on day 2 (6 drive-days,
    1 failure); model B has 2 drives/day and no failures (4 drive-days).
    Alibaba 2018-01-01..02: MA1 disks 1 and 2; disk 1 is labeled failed on 2018-01-05, so its
    failed_on is 2018-01-02 (last observed day on or before the label date).
    """
    raw = tmp_path / "raw"
    day1: list[BackblazeRow] = [
        ("A1", "A", CAP, 0),
        ("A2", "A", CAP, 0),
        ("A3", "A", CAP, 0),
        ("B1", "B", CAP, 0),
        ("B2", "B", CAP, 0),
    ]
    day2: list[BackblazeRow] = [("A1", "A", CAP, 1), *day1[1:]]
    write_backblaze_day(raw, date(2026, 1, 1), day1)
    write_backblaze_day(raw, date(2026, 1, 2), day2)
    write_alibaba_day(raw, date(2018, 1, 1), [(1, "MA1"), (2, "MA1")])
    write_alibaba_day(raw, date(2018, 1, 2), [(1, "MA1"), (2, "MA1")])
    write_alibaba_labels(raw, [("MA1", 1, "2018-01-05 00:00:00")])
    return raw


@pytest.fixture(scope="session")
def golden_raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Synthetic raw layer covering every model and period the drafted golden cases use.

    Two days per quarter; ST12000NM0008 has 1,200 drives (so a >= 1000-drive compare qualifies),
    other Backblaze models 70; every model fails 1-3 times per quarter so rate ratios exist.
    """
    raw = tmp_path_factory.mktemp("golden_raw")
    for (year, q), days in QUARTER_DAYS.items():
        for day_index, day in enumerate(days):
            rows: list[BackblazeRow] = []
            for mi, model in enumerate(BACKBLAZE_MODELS):
                n = 1200 if model == "ST12000NM0008" else 70
                fails = 1 + (mi + q + year) % 3 if day_index == 1 else 0
                rows.extend((f"S{mi}-{d}", model, CAP, 1 if d < fails else 0) for d in range(n))
            write_backblaze_day(raw, day, rows)
    labels: list[tuple[str, int, str]] = []
    for year in (2018, 2019):
        for day in (date(year, 1, 1), date(year, 12, 31)):
            rows_a: list[tuple[int, str]] = []
            for mi, model in enumerate(ALIBABA_MODELS):
                rows_a.extend((year * 1000 + mi * 100 + d, model) for d in range(70))
            write_alibaba_day(raw, day, rows_a)
        for mi, model in enumerate(ALIBABA_MODELS):
            labels.extend(
                (model, year * 1000 + mi * 100 + d, f"{year}-12-31 08:00:00")
                for d in range(1 + (mi + year) % 3)
            )
    write_alibaba_labels(raw, labels)
    return raw
