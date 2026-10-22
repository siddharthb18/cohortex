"""Build the configured provider from settings (`COHORTEX_LLM_MODE` = live | record | replay)."""

from __future__ import annotations

from cohortex_agent.config import Settings
from cohortex_agent.llm.base import LLMProvider
from cohortex_agent.llm.openai_compat import OpenAICompatibleProvider, SpendLedger
from cohortex_agent.llm.recording import RecordingProvider, ReplayProvider


def build_provider(settings: Settings, spend_ledger: SpendLedger | None = None) -> LLMProvider:
    if settings.llm_mode == "replay":
        return ReplayProvider(settings.llm_model, settings.recordings_dir)
    live = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        monthly_cap_usd=settings.monthly_llm_cap_usd,
        free_hosts=settings.free_llm_hosts,
        spend_ledger=spend_ledger,
        max_output_tokens=settings.llm_max_output_tokens,
        reasoning_effort=settings.llm_reasoning_effort,
        max_attempts=settings.llm_max_attempts,
        tpm_limit=settings.llm_tpm_limit,
    )
    if settings.llm_mode == "record":
        return RecordingProvider(live, settings.recordings_dir / settings.recordings_file)
    return live
