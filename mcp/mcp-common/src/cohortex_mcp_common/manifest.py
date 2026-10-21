"""Tool description pinning (FR-TOOL-5).

``contracts/tools/manifest.json`` holds every tool's description text with its SHA-256, and the
SHA-256 of the tool's input schema (canonical JSON). Servers read descriptions *from* the manifest
and refuse to start when a hash does not match, so an edited description or schema cannot reach
the model without a reviewed hash change in the same pull request.

Regenerate the hashes after an intentional edit::

    uv run python -m cohortex_mcp_common.manifest --write   # rewrite hashes
    uv run python -m cohortex_mcp_common.manifest --check   # CI: exit 1 on mismatch
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cohortex_mcp_common.contracts import (
    MANIFEST_FILE,
    contracts_dir,
    input_schema_file,
    load_json,
    tools_dir,
)


class ManifestMismatchError(RuntimeError):
    """A tool description or schema does not match its pinned hash; the server must not start."""


@dataclass(frozen=True)
class ToolContract:
    """One tool's pinned contract: name, LLM-facing description, input schema."""

    server: str
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """``<server>.<name>``, the envelope ``tool`` value (implementation-notes §6)."""
        return f"{self.server}.{self.name}"


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of UTF-8 text (how descriptions are hashed)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 kept (how schemas are hashed)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _manifest_path(base: Path | None) -> Path:
    return tools_dir(base) / MANIFEST_FILE


def _entries(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tools"), list):
        raise ManifestMismatchError("manifest.json must be an object with a 'tools' list")
    entries: list[dict[str, Any]] = []
    for entry in manifest["tools"]:
        if not isinstance(entry, dict):
            raise ManifestMismatchError("manifest.json 'tools' entries must be objects")
        entries.append(entry)
    return entries


def load_server_contracts(
    server: str, expected_tools: Sequence[str], base: Path | None = None
) -> dict[str, ToolContract]:
    """Load and verify the contracts of one server's tools.

    Raises:
        ManifestMismatchError: a description or schema hash differs from the manifest, or the
            manifest's tool set for ``server`` differs from ``expected_tools``.
    """
    root = base if base is not None else contracts_dir()
    entries = [e for e in _entries(load_json(_manifest_path(root))) if e.get("server") == server]
    listed = sorted(str(e.get("name")) for e in entries)
    if listed != sorted(expected_tools):
        raise ManifestMismatchError(
            f"manifest lists {listed} for server '{server}'; "
            f"code implements {sorted(expected_tools)}"
        )
    contracts: dict[str, ToolContract] = {}
    for entry in entries:
        name = str(entry["name"])
        description = str(entry.get("description", ""))
        if sha256_text(description) != entry.get("description_sha256"):
            raise ManifestMismatchError(
                f"description of {server}.{name} does not match its pinned SHA-256"
            )
        schema = load_json(tools_dir(root) / input_schema_file(server, name))
        if sha256_text(canonical_json(schema)) != entry.get("input_schema_sha256"):
            raise ManifestMismatchError(
                f"input schema of {server}.{name} does not match its pinned SHA-256"
            )
        contracts[name] = ToolContract(
            server=server,
            name=name,
            title=str(entry.get("title", name)),
            description=description,
            input_schema=schema,
        )
    return contracts


def regenerate(base: Path | None = None, *, write: bool) -> list[str]:
    """Recompute every hash in the manifest.

    Returns the qualified names whose hashes changed. With ``write=True`` the manifest file is
    rewritten (2-space indent, trailing newline) when anything changed.
    """
    root = base if base is not None else contracts_dir()
    path = _manifest_path(root)
    manifest = load_json(path)
    changed: list[str] = []
    for entry in _entries(manifest):
        server, name = str(entry["server"]), str(entry["name"])
        schema = load_json(tools_dir(root) / input_schema_file(server, name))
        description_hash = sha256_text(str(entry.get("description", "")))
        schema_hash = sha256_text(canonical_json(schema))
        if (
            entry.get("description_sha256") != description_hash
            or entry.get("input_schema_sha256") != schema_hash
        ):
            changed.append(f"{server}.{name}")
        entry["input_schema"] = input_schema_file(server, name)
        entry["description_sha256"] = description_hash
        entry["input_schema_sha256"] = schema_hash
    if write and changed:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``--check`` exits 1 when any hash is stale; ``--write`` rewrites stale hashes."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 when a hash is stale")
    mode.add_argument("--write", action="store_true", help="rewrite stale hashes")
    parser.add_argument("--contracts-dir", type=Path, default=None, help="contracts/ directory")
    args = parser.parse_args(argv)
    changed = regenerate(args.contracts_dir, write=bool(args.write))
    for name in changed:
        print(f"{'updated' if args.write else 'stale'}: {name}")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
