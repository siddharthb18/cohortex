"""Test helpers shared by the MCP packages' test suites (and agent-service tests)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from cohortex_mcp_common.contracts import (
    MANIFEST_FILE,
    contracts_dir,
    load_envelope_schema,
    load_error_schema,
)


def copy_contracts(destination: Path) -> Path:
    """Copy ``contracts/tools/`` under ``destination/contracts``; return that ``contracts`` dir."""
    target = destination / "contracts"
    shutil.copytree(contracts_dir() / "tools", target / "tools")
    return target


def edit_description(contracts: Path, qualified_name: str, new_text: str) -> None:
    """Change one tool's description in a copied manifest *without* updating its hash."""
    path = contracts / "tools" / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    server, name = qualified_name.split(".", 1)
    for entry in manifest["tools"]:
        if entry["server"] == server and entry["name"] == name:
            entry["description"] = new_text
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


INJECTION_STRINGS = (
    "x'; DROP TABLE drive; --",
    "1 OR 1=1",
    "SELECT * FROM drive",
    "../../etc/passwd",
    "C:\\Windows\\win.ini",
    "https://evil.example/payload",
    "file:///etc/passwd",
)


def example_arguments(qualified_name: str) -> dict[str, Any]:
    """The JSON example call embedded in a tool's manifest description (``Example: {...}``)."""
    manifest = json.loads((contracts_dir() / "tools" / MANIFEST_FILE).read_text(encoding="utf-8"))
    server, name = qualified_name.split(".", 1)
    for entry in manifest["tools"]:
        if entry["server"] == server and entry["name"] == name:
            example = str(entry["description"]).split("Example: ", 1)[1]
            parsed: dict[str, Any] = json.loads(example)
            return parsed
    raise KeyError(qualified_name)


def invalid_arguments(schema: dict[str, Any], valid: dict[str, Any]) -> list[Any]:
    """Arguments that a bounded schema must reject: wrong shapes, extra keys, bad values.

    Every case breaks exactly one rule of ``schema`` relative to the ``valid`` example.
    """
    cases: list[Any] = [[], "text", 1, True, {}, {**valid, "unexpected": 1}]
    cases.append({**valid, "sql": "SELECT 1"})
    bad_values: list[Any] = [
        None,
        [],
        {},
        True,
        "x" * 10_000,
        -1,
        10**20,
        1e308,
        *INJECTION_STRINGS,
    ]
    for key in schema.get("properties", {}):
        for value in bad_values:
            cases.append({**valid, key: value})
    for key in schema.get("required", []):
        cases.append({k: v for k, v in valid.items() if k != key})
    return cases


def assert_envelope(body: Any) -> None:
    """Raise ``AssertionError`` unless ``body`` matches ``envelope.schema.json``."""
    errors = list(Draft202012Validator(load_envelope_schema()).iter_errors(body))
    if errors:
        raise AssertionError(f"not a valid envelope: {errors[0].message}")


def assert_error_body(body: Any, code: str | None = None) -> None:
    """Raise ``AssertionError`` unless ``body`` matches ``error.schema.json`` (and ``code``)."""
    errors = list(Draft202012Validator(load_error_schema()).iter_errors(body))
    if errors:
        raise AssertionError(f"not a valid error body: {errors[0].message}")
    if code is not None and body["error"]["code"] != code:
        raise AssertionError(f"expected error code {code}, got {body['error']['code']}")
    if "Traceback" in body["error"]["message"]:
        raise AssertionError("error message contains a stack trace")
