"""Locate shared repository files (contracts, migrations) and the raw-layer root."""

from __future__ import annotations

from pathlib import Path


def find_repo_file(relative: str) -> Path:
    """Find ``relative`` in the nearest ancestor of this package or of the working directory."""
    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    for start in starts:
        for base in (start, *start.parents):
            candidate = base / relative
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"{relative} not found above {starts[0]} or {starts[1]}")


def is_remote(uri: str) -> bool:
    return "://" in uri and not uri.startswith("file://")


def local_raw_root(raw_uri: str) -> Path:
    """The raw layer as a local directory. Writing to object stores is not supported yet."""
    if is_remote(raw_uri):
        raise ValueError(f"writing the raw layer requires a local RAW_DATA_URI, got {raw_uri!r}")
    path = raw_uri.removeprefix("file://")
    return Path(path).resolve()


def duckdb_raw_uri(raw_uri: str) -> str:
    """The `{raw}` substitution for views.sql: absolute for local paths, untouched for URIs."""
    if is_remote(raw_uri):
        return raw_uri.rstrip("/")
    return local_raw_root(raw_uri).as_posix()
