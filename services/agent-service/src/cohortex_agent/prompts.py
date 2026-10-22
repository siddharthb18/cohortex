"""Versioned prompt files (`prompts/<node>.<version>.md`) and their SHA-256 hashes (NFR-MAINT-2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPT_VERSION = "v1"
COMMON_PROMPTS = ("refusal", "drafter", "revise", "repair")
MODE_PROMPTS: dict[str, tuple[str, ...]] = {
    "single": ("agent",),
    "orchestrated": ("planner", "worker"),
}


class PromptMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str  # e.g. "drafter.v1"
    text: str
    sha256: str


class PromptStore:
    """Loads prompt files once; `hashes(mode)` is what each investigation row records."""

    def __init__(self, directory: Path, version: str = PROMPT_VERSION) -> None:
        self._dir = directory
        self._version = version
        self._prompts: dict[str, Prompt] = {}
        for node in sorted({*COMMON_PROMPTS, *(n for v in MODE_PROMPTS.values() for n in v)}):
            path = directory / f"{node}.{version}.md"
            if not path.is_file():
                raise PromptMissingError(f"prompt file missing: {path}")
            raw = path.read_bytes()
            self._prompts[node] = Prompt(
                name=f"{node}.{version}",
                text=raw.decode("utf-8").strip(),
                sha256=hashlib.sha256(raw).hexdigest(),
            )

    def text(self, node: str) -> str:
        return self._prompts[node].text

    def hashes(self, mode: str) -> dict[str, str]:
        nodes = (*COMMON_PROMPTS, *MODE_PROMPTS[mode])
        return {self._prompts[n].name: self._prompts[n].sha256 for n in sorted(nodes)}
