"""Deterministic synthetic data in the exact file formats of the real sources.

The real Backblaze and Tianchi downloads are not reachable from every build environment, so
tests and the committed fixture use synthetic data. It is clearly labelled as synthetic
(`fixture.json`, model names start with `SYN-`) and must never be read as real fleet behavior.

Backblaze format: one `YYYY-MM-DD.csv` per day, one row per operational drive, columns
`date, serial_number, model, capacity_bytes, failure, datacenter, cluster_id, vault_id, pod_id,
pod_slot_num, is_legacy_format, smart_{id}_normalized, smart_{id}_raw, ...`. `failure` is 1 on a
drive's last operational day; the drive does not appear afterwards.

Alibaba format: one `YYYYMMDD.csv` per sampling day with `disk_id, ds, model, n_{id}, r_{id}, ...`
and `ssd_failure_label.csv` with `model, disk_id, failure_time`.
"""

from __future__ import annotations

import csv
import gzip
import io
import random
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO, Literal

from cohortex_ingest.quarters import Quarter

Vendor = Literal["seagate", "hgst", "toshiba", "wdc"]

NON_SMART_HEADER = (
    "date",
    "serial_number",
    "model",
    "capacity_bytes",
    "failure",
    "datacenter",
    "cluster_id",
    "vault_id",
    "pod_id",
    "pod_slot_num",
    "is_legacy_format",
)
SMART_IDS = (1, 3, 5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242)
SEAGATE_ONLY = frozenset({187, 188, 240, 241, 242})
DATACENTERS = ("ams5", "iad1", "phx1", "sac0", "sac2")
SERIAL_PREFIX: dict[str, str] = {"seagate": "ZL", "hgst": "8H", "toshiba": "X0", "wdc": "2B"}

ALIBABA_MODELS = ("MA1", "MA2", "MB1", "MB2", "MC1", "MC2")
ALIBABA_ATTRS = (1, 5, 9, 12, 171, 172, 173, 174, 175, 183, 187, 188, 194, 195, 199)


@dataclass(frozen=True)
class SyntheticModel:
    name: str
    capacity_bytes: int
    n_drives: int
    monthly_failures: tuple[int, int, int]
    vendor: Vendor = "seagate"


# A handful of models; SYN-ST16000 has a clear AFR step change after the quarter's first month.
DEFAULT_MODELS: tuple[SyntheticModel, ...] = (
    SyntheticModel("SYN-ST12000", 12_000_138_625_024, 90, (1, 0, 1), "seagate"),
    SyntheticModel("SYN-HUH721212", 12_000_138_625_024, 70, (0, 1, 0), "hgst"),
    SyntheticModel("SYN-MG08ACA16", 16_000_900_661_248, 60, (1, 0, 0), "toshiba"),
    SyntheticModel("SYN-WUH721816", 16_000_900_661_248, 50, (0, 0, 1), "wdc"),
    SyntheticModel("SYN-ST16000", 16_000_900_661_248, 90, (0, 3, 4), "seagate"),
)


@dataclass
class ModelSummary:
    drives: int = 0
    drive_days: int = 0
    failures: int = 0
    monthly_failures: list[int] = field(default_factory=lambda: [0, 0, 0])


@dataclass
class SyntheticSummary:
    quarter: str
    days: int
    files: list[Path]
    models: dict[str, ModelSummary]
    failed: dict[str, date]  # serial -> failure day
    serial_model: dict[str, str]


@dataclass
class _Drive:
    serial: str
    model: SyntheticModel
    first: date
    fail: date | None
    warns: bool
    poh0: int
    temp: int
    cycles: int
    load0: int
    smart1: int
    lba0: int
    dc: str
    cluster: int
    vault: int
    pod: int
    slot: int


def _open_text(path: Path, gz: bool) -> IO[str]:
    if not gz:
        return path.open("w", encoding="utf-8", newline="")
    raw = path.open("wb")
    # filename="" and mtime=0 keep the bytes deterministic.
    zipped = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9)
    return io.TextIOWrapper(zipped, encoding="utf-8", newline="")


def _unique_serial(rng: random.Random, prefix: str, used: set[str]) -> str:
    while True:
        serial = f"{prefix}{rng.randrange(16**7):07X}"
        if serial not in used:
            used.add(serial)
            return serial


def _smart_row(d: _Drive, day: date, t: int) -> list[str]:
    bump = 0
    if d.fail is not None and d.warns:
        to_fail = (d.fail - day).days
        if to_fail <= 13:
            bump = 14 - to_fail
    poh = d.poh0 + 24 * t
    temp = d.temp + (t * 7 + d.cycles) % 3 - 1
    seagate = d.model.vendor == "seagate"
    values: dict[int, tuple[int, int]] = {
        1: (80, d.smart1) if seagate else (100, 0),
        3: (91, 0) if seagate else (100, 0),
        5: (100 - min(bump, 50), bump * 8),
        9: (max(1, 100 - poh // 1000), poh),
        12: (100, d.cycles),
        187: (100 - bump, bump * 2),
        188: (100, 0),
        193: (max(1, 100 - (d.load0 + 3 * t) // 2000), d.load0 + 3 * t),
        194: (temp, temp) if seagate else (min(253, 200 - temp), temp),
        197: (100, bump * 4),
        198: (100, bump * 4),
        199: (200, 0),
        240: (100, poh - 50),
        241: (100, d.lba0 + 1_900_000_000 * t),
        242: (100, d.lba0 * 2 + 4_100_000_000 * t),
    }
    out: list[str] = []
    for attr in SMART_IDS:
        if attr in SEAGATE_ONLY and not seagate:
            out += ["", ""]
        else:
            norm, raw = values[attr]
            out += [str(norm), str(raw)]
    return out


def backblaze_header() -> list[str]:
    smart = [f"smart_{a}_{kind}" for a in SMART_IDS for kind in ("normalized", "raw")]
    return [*NON_SMART_HEADER, *smart]


def generate_backblaze_quarter(
    out_dir: Path,
    quarter: str | Quarter,
    *,
    seed: int,
    models: Sequence[SyntheticModel] = DEFAULT_MODELS,
    gz: bool = False,
) -> SyntheticSummary:
    """Write one Backblaze-format CSV per day of ``quarter`` into ``out_dir``."""
    q = quarter if isinstance(quarter, Quarter) else Quarter.parse(quarter)
    rng = random.Random(f"cohortex-synthetic:{seed}:{q.label}")  # noqa: S311 - test data, not crypto
    days = q.days()
    months = [[d for d in days if d.month == m] for m in sorted({d.month for d in days})]
    used: set[str] = set()
    drives: list[_Drive] = []
    summary = SyntheticSummary(q.label, len(days), [], {}, {}, {})
    for m in models:
        summary.models[m.name] = ModelSummary()
        model_drives: list[_Drive] = []
        for _ in range(m.n_drives):
            first = days[0] if rng.random() < 0.9 else rng.choice(days[: len(days) * 2 // 3])
            model_drives.append(
                _Drive(
                    serial=_unique_serial(rng, SERIAL_PREFIX[m.vendor], used),
                    model=m,
                    first=first,
                    fail=None,
                    warns=rng.random() < 0.6,
                    poh0=rng.randrange(2_000, 40_000),
                    temp=rng.randrange(22, 37),
                    cycles=rng.randrange(2, 40),
                    load0=rng.randrange(50, 9_000),
                    smart1=rng.randrange(10_000_000, 200_000_000),
                    lba0=rng.randrange(10**10, 10**11),
                    dc=rng.choice(DATACENTERS),
                    cluster=rng.randrange(0, 4),
                    vault=rng.randrange(1_000, 1_100),
                    pod=rng.randrange(0, 20),
                    slot=rng.randrange(0, 60),
                )
            )
        for month_days, k in zip(months, m.monthly_failures, strict=True):
            candidates = [d for d in model_drives if d.fail is None and d.first <= month_days[-1]]
            for d in rng.sample(candidates, k):
                d.fail = rng.choice([x for x in month_days if x >= d.first])
        drives.extend(model_drives)

    out_dir.mkdir(parents=True, exist_ok=True)
    header = backblaze_header()
    for t, day in enumerate(days):
        path = out_dir / f"{day.isoformat()}.csv{'.gz' if gz else ''}"
        with _open_text(path, gz) as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(header)
            for d in drives:
                if day < d.first or (d.fail is not None and day > d.fail):
                    continue
                failed_today = d.fail == day
                writer.writerow(
                    [
                        day.isoformat(),
                        d.serial,
                        d.model.name,
                        str(d.model.capacity_bytes),
                        "1" if failed_today else "0",
                        d.dc,
                        str(d.cluster),
                        str(d.vault),
                        str(d.pod),
                        str(d.slot),
                        "0",
                        *_smart_row(d, day, t),
                    ]
                )
                ms = summary.models[d.model.name]
                ms.drive_days += 1
                if failed_today:
                    ms.failures += 1
                    ms.monthly_failures[day.month - q.start.month] += 1
        summary.files.append(path)
    for d in drives:
        summary.models[d.model.name].drives += 1
        summary.serial_model[d.serial] = d.model.name
        if d.fail is not None:
            summary.failed[d.serial] = d.fail
    return summary


def zip_quarter(src_dir: Path, zip_path: Path, quarter: str | Quarter) -> Path:
    """Package daily CSVs like Backblaze's quarterly ZIP (`data_Qn_YYYY/YYYY-MM-DD.csv`)."""
    q = quarter if isinstance(quarter, Quarter) else Quarter.parse(quarter)
    folder = q.zip_name.removesuffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.iterdir()):
            if path.name.endswith(".csv.gz"):
                data = gzip.decompress(path.read_bytes())
                name = path.name.removesuffix(".gz")
            elif path.name.endswith(".csv"):
                data = path.read_bytes()
                name = path.name
            else:
                continue
            info = zipfile.ZipInfo(f"{folder}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return zip_path


# ---------------------------------------------------------------------------------- Alibaba


@dataclass
class AlibabaSummary:
    files: list[Path]
    label_file: Path
    drive_days: dict[str, int]  # per model
    labels: list[tuple[str, str, date]]  # model, disk_id, failure date
    expected_failed_on: dict[str, date]  # drive_id (model:disk_id) -> failed_on


def generate_alibaba(
    out_dir: Path,
    *,
    seed: int,
    start: date = date(2018, 3, 17),
    n_days: int = 30,
    drives_per_model: int = 8,
    gz: bool = False,
) -> AlibabaSummary:
    """Write Tianchi-format SMART day files and `ssd_failure_label.csv` for six SSD models.

    The default range crosses a quarter boundary (2018Q1 → 2018Q2). Disk IDs repeat across
    models on purpose: only `model:disk_id` identifies a drive. Each model has one failure whose
    label time is on or a few days after the drive's last observed day; a few drive-days are
    missing at random, as in the real logs.
    """
    rng = random.Random(f"cohortex-synthetic-alibaba:{seed}")  # noqa: S311 - test data
    days = [start + timedelta(days=i) for i in range(n_days)]
    observed: dict[tuple[str, str], list[date]] = {}
    labels: list[tuple[str, str, date]] = []
    expected: dict[str, date] = {}
    state: dict[tuple[str, str], tuple[int, int, int]] = {}
    for model in ALIBABA_MODELS:
        disk_ids = [str(i) for i in rng.sample(range(1, 3 * drives_per_model), drives_per_model)]
        failing = rng.choice(disk_ids)
        for disk in disk_ids:
            last = days[-1]
            if disk == failing:
                last = days[rng.randrange(n_days // 3, n_days - 2)]
            seen = [d for d in days if d <= last and (d == last or rng.random() > 0.04)]
            observed[(model, disk)] = seen
            state[(model, disk)] = (
                rng.randrange(500, 20_000),
                rng.randrange(30, 45),
                rng.randrange(1, 60),
            )
            if disk == failing:
                label_day = last + timedelta(days=rng.choice((0, 0, 1, 3)))
                labels.append((model, disk, label_day))
                expected[f"{model}:{disk}"] = last

    out_dir.mkdir(parents=True, exist_ok=True)
    header = ["disk_id", "ds", "model"]
    for a in ALIBABA_ATTRS:
        header += [f"n_{a}", f"r_{a}"]
    drive_days = dict.fromkeys(ALIBABA_MODELS, 0)
    files: list[Path] = []
    for t, day in enumerate(days):
        path = out_dir / f"{day:%Y%m%d}.csv{'.gz' if gz else ''}"
        with _open_text(path, gz) as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(header)
            for (model, disk), seen in observed.items():
                if day not in seen:
                    continue
                poh0, temp, cycles = state[(model, disk)]
                row = [disk, f"{day:%Y%m%d}", model]
                for a in ALIBABA_ATTRS:
                    raw = {9: poh0 + 24 * t, 12: cycles, 194: temp, 241: 0}.get(a, 0)
                    if a in (173, 174):
                        raw = 3 * t + cycles
                    row += [str(100 if a != 194 else 100 - temp // 2), str(raw)]
                writer.writerow(row)
                drive_days[model] += 1
        files.append(path)
    label_file = out_dir / "ssd_failure_label.csv"
    with label_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["model", "disk_id", "failure_time"])
        for model, disk, day in labels:
            ts = datetime(day.year, day.month, day.day, rng.randrange(24), rng.randrange(60))
            writer.writerow([model, disk, ts.strftime("%Y-%m-%d %H:%M:%S")])
    return AlibabaSummary(files, label_file, drive_days, labels, expected)
