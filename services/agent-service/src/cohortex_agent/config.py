"""Service configuration, read once from the environment (twelve-factor, ERS §3).

Every variable is listed in the component README and in the root `.env.example`.
Defaults follow docs/implementation-notes.md §7.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

LLMMode = Literal["live", "record", "replay"]
Mode = Literal["single", "orchestrated"]
ToolsBackend = Literal["mcp", "fake"]


class ConfigError(ValueError):
    """Raised when a required variable is missing or malformed (fail fast)."""


def _find_prompts_dir() -> Path:
    """Locate the repo's `prompts/` directory by walking up from this file, then the CWD."""
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (start, *start.parents):
            candidate = parent / "prompts"
            if (candidate / "agent.v1.md").is_file():
                return candidate
    return Path.cwd() / "prompts"


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _csv(env: Mapping[str, str], name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = env.get(name)
    if raw is None:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _choice[T: str](env: Mapping[str, str], name: str, default: T, allowed: tuple[T, ...]) -> T:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    for option in allowed:
        if raw == option:
            return option
    raise ConfigError(f"{name} must be one of {list(allowed)}, got {raw!r}")


@dataclass(frozen=True)
class Settings:
    """All agent-service settings. Build with `Settings.from_env()`; tests construct directly."""

    database_url: str
    env: str = "local"
    # LLM provider (ADR-010, ADR-013)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 2048
    llm_reasoning_effort: str = ""
    llm_max_attempts: int = 3
    llm_temperature: float = 0.0
    llm_mode: LLMMode = "live"
    recordings_dir: Path = Path("evals/recordings")
    recordings_file: str = "agent-service.jsonl"
    monthly_llm_cap_usd: float = 0.0
    free_llm_hosts: tuple[str, ...] = ()
    # Budgets (FR-AGT-8)
    max_tool_calls: int = 20
    max_input_tokens: int = 150_000
    max_seconds: float = 180.0
    # Tools (ADR-012)
    tools_backend: ToolsBackend = "mcp"
    mcp_fleet_url: str = "http://localhost:8101/mcp"
    mcp_stats_url: str = "http://localhost:8102/mcp"
    mcp_docs_url: str | None = None
    mcp_timeout_seconds: float = 30.0
    tool_fixtures_dir: Path | None = None  # eval-harness hook; ignored in demo
    # API
    default_mode: Mode = "single"
    public_mode: Mode = "single"
    public_rate_limit_per_day: int = 5
    admin_token: str | None = None
    trust_proxy: bool = False
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    prompts_dir: Path = field(default_factory=_find_prompts_dir)

    @property
    def is_demo(self) -> bool:
        return self.env == "demo"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = dict(os.environ if env is None else env)
        database_url = e.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("DATABASE_URL is required")
        modes: tuple[Mode, ...] = ("single", "orchestrated")
        prompts_dir = e.get("COHORTEX_PROMPTS_DIR", "").strip()
        fixtures_dir = e.get("COHORTEX_TOOL_FIXTURES_DIR", "").strip()
        return cls(
            database_url=database_url,
            env=e.get("COHORTEX_ENV", "local").strip() or "local",
            llm_base_url=e.get("LLM_BASE_URL", cls.llm_base_url).strip(),
            llm_model=e.get("LLM_MODEL", cls.llm_model).strip(),
            llm_api_key=e.get("LLM_API_KEY", ""),
            llm_timeout_seconds=_float(e, "LLM_TIMEOUT_SECONDS", 60.0),
            llm_max_output_tokens=_int(e, "LLM_MAX_OUTPUT_TOKENS", 2048),
            llm_reasoning_effort=e.get("LLM_REASONING_EFFORT", "").strip(),
            llm_max_attempts=_int(e, "LLM_MAX_ATTEMPTS", 3),
            llm_temperature=_float(e, "LLM_TEMPERATURE", 0.0),
            llm_mode=_choice(e, "COHORTEX_LLM_MODE", "live", ("live", "record", "replay")),
            recordings_dir=Path(e.get("COHORTEX_RECORDINGS_DIR", "evals/recordings")),
            recordings_file=e.get("COHORTEX_RECORDINGS_FILE", "agent-service.jsonl"),
            monthly_llm_cap_usd=_float(e, "COHORTEX_MONTHLY_LLM_CAP_USD", 0.0),
            free_llm_hosts=_csv(e, "COHORTEX_FREE_LLM_HOSTS", ()),
            max_tool_calls=_int(e, "COHORTEX_MAX_TOOL_CALLS", 20),
            max_input_tokens=_int(e, "COHORTEX_MAX_INPUT_TOKENS", 150_000),
            max_seconds=_float(e, "COHORTEX_MAX_SECONDS", 180.0),
            tools_backend=_choice(e, "COHORTEX_TOOLS_BACKEND", "mcp", ("mcp", "fake")),
            mcp_fleet_url=e.get("MCP_FLEET_URL", cls.mcp_fleet_url).strip(),
            mcp_stats_url=e.get("MCP_STATS_URL", cls.mcp_stats_url).strip(),
            mcp_docs_url=(e.get("MCP_DOCS_URL", "").strip() or None),
            mcp_timeout_seconds=_float(e, "MCP_TIMEOUT_SECONDS", 30.0),
            tool_fixtures_dir=Path(fixtures_dir) if fixtures_dir else None,
            default_mode=_choice(e, "COHORTEX_DEFAULT_MODE", "single", modes),
            public_mode=_choice(e, "COHORTEX_PUBLIC_MODE", "single", modes),
            public_rate_limit_per_day=_int(e, "COHORTEX_PUBLIC_RATE_LIMIT_PER_DAY", 5),
            admin_token=(e.get("ADMIN_TOKEN", "").strip() or None),
            trust_proxy=_bool(e, "COHORTEX_TRUST_PROXY", False),
            cors_origins=_csv(e, "COHORTEX_CORS_ORIGINS", ("http://localhost:5173",)),
            prompts_dir=Path(prompts_dir) if prompts_dir else _find_prompts_dir(),
        )
