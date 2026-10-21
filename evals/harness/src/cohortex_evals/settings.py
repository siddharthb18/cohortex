"""Environment settings and repository paths."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AGENT_API_URL = "http://localhost:8000"
DEFAULT_RAW_DATA_URI = "./data/raw"
VIEWS_RELPATH = Path("contracts/rawlayer/views.sql")


@dataclass(frozen=True)
class Settings:
    agent_api_url: str
    raw_data_uri: str
    database_url: str | None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            agent_api_url=os.environ.get("AGENT_API_URL", DEFAULT_AGENT_API_URL).rstrip("/"),
            raw_data_uri=os.environ.get("RAW_DATA_URI", DEFAULT_RAW_DATA_URI),
            database_url=os.environ.get("DATABASE_URL") or None,
        )


def repo_root(start: Path | None = None) -> Path:
    """Nearest ancestor (of ``start``, the CWD, then this file) holding the raw-layer views."""
    candidates = [start or Path.cwd(), Path(__file__).resolve()]
    for origin in candidates:
        for directory in [origin, *origin.parents]:
            if (directory / VIEWS_RELPATH).is_file():
                return directory
    raise FileNotFoundError(f"cannot find {VIEWS_RELPATH} above {candidates[0]}")


@dataclass(frozen=True)
class RepoPaths:
    root: Path

    @property
    def views_sql(self) -> Path:
        return self.root / VIEWS_RELPATH

    @property
    def golden_v1(self) -> Path:
        return self.root / "evals/golden/v1/cases.jsonl"

    @property
    def adversarial_cases(self) -> Path:
        return self.root / "evals/adversarial/cases.jsonl"

    @property
    def case_schema(self) -> Path:
        return self.root / "evals/golden/case.schema.json"

    @property
    def thresholds(self) -> Path:
        return self.root / "evals/harness/thresholds.json"

    @property
    def baseline_v1(self) -> Path:
        return self.root / "evals/baselines/v1.json"

    @property
    def reports_dir(self) -> Path:
        return self.root / "evals/reports"

    @classmethod
    def discover(cls) -> RepoPaths:
        return cls(repo_root())


def git_sha(root: Path) -> str:
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"
