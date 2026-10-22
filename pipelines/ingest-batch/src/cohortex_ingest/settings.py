"""Configuration from environment variables (ERS §5; twelve-factor)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_url: str | None = None
    raw_data_uri: str = "./data/raw"
    embedding_dim: int = Field(default=384, gt=0)
    window_quarters: int = Field(default=6, gt=0)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        try:
            return cls(
                database_url=env.get("DATABASE_URL") or None,
                raw_data_uri=env.get("RAW_DATA_URI") or "./data/raw",
                embedding_dim=int(env.get("EMBEDDING_DIM") or 384),
                window_quarters=int(env.get("COHORTEX_WINDOW_QUARTERS") or 6),
            )
        except ValueError as exc:
            raise ConfigError(f"invalid configuration: {exc}") from exc

    def require_database_url(self) -> str:
        if not self.database_url:
            raise ConfigError("DATABASE_URL is not set")
        return self.database_url
