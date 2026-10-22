"""Download a Backblaze quarter ZIP and verify it (FR-ING-1).

Verification: HTTP status, byte count against `Content-Length`, an optional expected SHA-256,
and the ZIP's own CRC check of every member. The file is written as `<name>.part` and renamed
only after it passes. Resuming an interrupted download is not supported.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from cohortex_ingest.quarters import Quarter

log = logging.getLogger(__name__)

BACKBLAZE_BASE_URL = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data"
CHUNK = 1 << 20


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Download:
    url: str
    path: Path
    bytes: int
    sha256: str


def quarter_url(quarter: Quarter) -> str:
    return f"{BACKBLAZE_BASE_URL}/{quarter.zip_name}"


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def verify_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
    except (zipfile.BadZipFile, zlib.error, OSError, EOFError) as exc:
        raise DownloadError(f"{path.name} is not a valid ZIP file: {exc}") from exc
    if bad is not None:
        raise DownloadError(f"{path.name}: ZIP member {bad} fails its CRC check")


def download(
    url: str,
    dest_dir: Path,
    *,
    client: httpx.Client | None = None,
    expected_sha256: str | None = None,
) -> Download:
    name = Path(urlparse(url).path).name
    if not name:
        raise DownloadError(f"cannot derive a file name from {url}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    part = dest_dir / f"{name}.part"
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0))
    digest = hashlib.sha256()
    size = 0
    try:
        with http.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise DownloadError(f"GET {url} returned HTTP {resp.status_code}")
            declared = resp.headers.get("Content-Length")
            with part.open("wb") as fh:
                for chunk in resp.iter_bytes(CHUNK):
                    fh.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        if declared is not None and int(declared) != size:
            raise DownloadError(f"size mismatch: Content-Length {declared}, received {size}")
        sha = digest.hexdigest()
        if expected_sha256 and expected_sha256.lower() != sha:
            raise DownloadError(f"SHA-256 mismatch: expected {expected_sha256}, got {sha}")
        verify_zip(part)
        part.replace(final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        if own_client:
            http.close()
    log.info("downloaded %s (%d bytes, sha256 %s)", url, size, sha)
    return Download(url, final, size, sha)
