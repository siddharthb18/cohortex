"""FR-ING-1: download a named Backblaze quarter, verify it, and record source URL, bytes and
SHA-256 in `ingest_run`. Acceptance: a fixture quarter run creates one complete `ingest_run` row."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import httpx
import psycopg
import pytest
from cohortex_ingest.download import DownloadError, download, quarter_url
from cohortex_ingest.pipeline import backfill
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.schema import UnknownColumnError
from cohortex_ingest.settings import Settings
from cohortex_ingest.synthetic import SyntheticSummary, zip_quarter

Q2 = Quarter.parse("2026Q2")
URL = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_Q2_2026.zip"


@pytest.fixture(scope="module")
def q2_zip(
    synthetic_q2: tuple[Path, SyntheticSummary], tmp_path_factory: pytest.TempPathFactory
) -> bytes:
    src, _ = synthetic_q2
    path = zip_quarter(src, tmp_path_factory.mktemp("zip") / "data_Q2_2026.zip", Q2)
    return path.read_bytes()


def _client(body: bytes, *, status: int = 200, length: int | None = None) -> httpx.Client:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        headers = {"Content-Length": str(len(body) if length is None else length)}
        return httpx.Response(status, content=body, headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen  # type: ignore[attr-defined]
    return client


def test_quarter_url_follows_backblaze_pattern() -> None:
    assert quarter_url(Q2) == URL
    assert quarter_url(Quarter.parse("2019Q4")).endswith("/data_Q4_2019.zip")


def test_download_streams_and_hashes(q2_zip: bytes, tmp_path: Path) -> None:
    result = download(URL, tmp_path, client=_client(q2_zip))
    assert result.path == tmp_path / "data_Q2_2026.zip"
    assert result.path.read_bytes() == q2_zip
    assert result.bytes == len(q2_zip)
    assert result.sha256 == hashlib.sha256(q2_zip).hexdigest()
    assert not list(tmp_path.glob("*.part"))


def test_http_error_fails(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="404"):
        download(URL, tmp_path, client=_client(b"nope", status=404))
    assert not list(tmp_path.iterdir())


def test_size_mismatch_fails(q2_zip: bytes, tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="size"):
        download(URL, tmp_path, client=_client(q2_zip, length=len(q2_zip) + 10))


def test_checksum_mismatch_fails(q2_zip: bytes, tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="SHA-256"):
        download(URL, tmp_path, client=_client(q2_zip), expected_sha256="0" * 64)


def test_corrupt_zip_fails(q2_zip: bytes, tmp_path: Path) -> None:
    corrupt = bytearray(q2_zip)
    corrupt[200:260] = b"\x00" * 60  # inside the first member's compressed data
    with pytest.raises(DownloadError, match="ZIP"):
        download(URL, tmp_path, client=_client(bytes(corrupt)))
    with pytest.raises(DownloadError, match="ZIP"):
        download(URL, tmp_path, client=_client(b"not a zip at all"))


def test_backfill_creates_one_complete_ingest_run(
    q2_zip: bytes, settings: Settings, pg: psycopg.Connection, tmp_path: Path
) -> None:
    client = _client(q2_zip)
    outcome = backfill(settings, Q2, dest=tmp_path / "downloads", client=client)
    assert client.seen == [URL]  # type: ignore[attr-defined]
    assert outcome.status == "succeeded"
    rows = pg.execute(
        "SELECT id, source, period, source_url, bytes, sha256, schema_version, started_at, "
        "finished_at, status, reconciliation FROM ingest_run"
    ).fetchall()
    assert len(rows) == 1
    (run_id, source, period, url, nbytes, sha, version, started, finished, status, rec) = rows[0]
    assert run_id == outcome.run_id
    assert (source, period, url, status) == ("backblaze", "2026Q2", URL, "succeeded")
    assert nbytes == len(q2_zip)
    assert sha == hashlib.sha256(q2_zip).hexdigest()
    assert version is not None
    assert len(version) == 12
    assert started <= finished
    assert rec["ok"] is True
    assert len(rec["models"]) == 3


def test_backfill_with_bad_column_records_failed_run(
    synthetic_q2: tuple[Path, SyntheticSummary],
    settings: Settings,
    pg: psycopg.Connection,
    tmp_path: Path,
) -> None:
    src, _ = synthetic_q2
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    day = bad / "2026-06-01.csv"
    header, *rest = day.read_text().splitlines()
    day.write_text("\n".join([header + ",rack_label", *(r + ",r1" for r in rest)]) + "\n")
    body = zip_quarter(bad, tmp_path / "data_Q2_2026.zip", Q2).read_bytes()
    with pytest.raises(UnknownColumnError, match="rack_label"):
        backfill(settings, Q2, dest=tmp_path / "downloads", client=_client(body))
    rows = pg.execute("SELECT status, finished_at, reconciliation FROM ingest_run").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "failed"
    assert rows[0][1] is not None
    assert rows[0][2] is None
    assert pg.execute("SELECT count(*) FROM cohort_daily").fetchone() == (0,)
