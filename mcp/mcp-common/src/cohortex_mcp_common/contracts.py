"""Locate and load the tool contracts in ``contracts/tools/``.

The directory is ``$COHORTEX_CONTRACTS_DIR`` when that variable is set (containers set it), else
the repository's ``contracts/`` directory found by walking up from this file (works for the uv
workspace's editable installs).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

CONTRACTS_DIR_ENV = "COHORTEX_CONTRACTS_DIR"
MANIFEST_FILE = "manifest.json"
ENVELOPE_SCHEMA_FILE = "envelope.schema.json"
ERROR_SCHEMA_FILE = "error.schema.json"


class ContractsNotFoundError(RuntimeError):
    """``contracts/tools/manifest.json`` could not be found."""


def contracts_dir() -> Path:
    """Return the ``contracts/`` directory (the parent of ``tools/``)."""
    configured = os.environ.get(CONTRACTS_DIR_ENV)
    if configured:
        path = Path(configured)
        if not (path / "tools" / MANIFEST_FILE).is_file():
            raise ContractsNotFoundError(
                f"{CONTRACTS_DIR_ENV}={configured} has no tools/{MANIFEST_FILE}"
            )
        return path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts"
        if (candidate / "tools" / MANIFEST_FILE).is_file():
            return candidate
    raise ContractsNotFoundError(
        f"contracts/tools/{MANIFEST_FILE} not found; set {CONTRACTS_DIR_ENV}"
    )


def tools_dir(base: Path | None = None) -> Path:
    """Return ``contracts/tools/`` under ``base`` (default: :func:`contracts_dir`)."""
    return (base if base is not None else contracts_dir()) / "tools"


def load_json(path: Path) -> Any:
    """Read a UTF-8 JSON file."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def input_schema_file(server: str, name: str) -> str:
    """File name of a tool's input schema, e.g. ``fleet.cohort_afr.input.schema.json``."""
    return f"{server}.{name}.input.schema.json"


def load_input_schema(server: str, name: str, base: Path | None = None) -> dict[str, Any]:
    """Load one tool's input JSON Schema."""
    return cast(dict[str, Any], load_json(tools_dir(base) / input_schema_file(server, name)))


def load_envelope_schema(base: Path | None = None) -> dict[str, Any]:
    """Load the result envelope JSON Schema."""
    return cast(dict[str, Any], load_json(tools_dir(base) / ENVELOPE_SCHEMA_FILE))


def load_error_schema(base: Path | None = None) -> dict[str, Any]:
    """Load the structured error body JSON Schema."""
    return cast(dict[str, Any], load_json(tools_dir(base) / ERROR_SCHEMA_FILE))
