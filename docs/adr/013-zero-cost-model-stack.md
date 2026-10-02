# ADR-013: Zero-cost model stack: open-weight models behind OpenAI-compatible endpoints

- **Status:** Proposed
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)
- **Builds on:** ADR-010 (one provider interface). Does not change any Accepted ADR.

## Context

The budget is $0. A Claude Pro or Max subscription cannot power the app: Anthropic's Consumer Terms
limit subscription use to Claude's own apps, and third-party or Agent SDK use of subscription tokens
is not allowed (API keys are billed separately). So the app needs models that cost nothing to call.

Free options checked on 2026-10-02:

| Option | What it gives | Limits / catch |
| --- | --- | --- |
| Groq free tier | `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, OpenAI-compatible API | Per model: 30 req/min, 1K req/day, 8K tokens/min, 200K tokens/day |
| Ollama (local, v0.35) | `gpt-oss:20b` and others offline, OpenAI-compatible at `/v1` | Needs about 16 GB of RAM or VRAM; slow on CPU |
| vLLM 0.30 on TAMU HPRC (Grace, A100) | Same open weights at full speed, OpenAI-compatible server | Needs an HPRC allocation and batch scheduling |
| Google Gemini free tier | Strong closed models | Free-tier prompts may be used for training; closed weights hurt reproducibility |
| Cerebras, GitHub Models | — | Cerebras is a trial only; GitHub Models was retired on 2026-07-30 |

## Decision

1. The agent model is **`gpt-oss-20b`** (open weights, Apache-2.0), reached only through an
   OpenAI-compatible endpoint. The same weights run in three places:
   - **Development:** Groq free tier (`openai/gpt-oss-20b`).
   - **Offline development:** local Ollama (`gpt-oss:20b`).
   - **Graded eval runs and the experiment (WP-18):** vLLM on HPRC, so results are reproducible
     and not limited by free-tier quotas. This also feeds WP-19.
2. The **judge** uses a different model family from the agent, to reduce self-preference:
   `qwen/qwen3.8-27b` on Groq, or the same model on HPRC.
3. **Embeddings** use `BAAI/bge-small-en-v1.5` (384 dimensions) run locally with `fastembed`; no API.
4. **CI** uses recorded responses only (already in ERS); the optional nightly live subset runs only
   against a free tier or HPRC.
5. The provider interface (ADR-010) is implemented with the `openai` Python SDK against
   `LLM_BASE_URL`. No paid provider is configured; the spend cap defaults to 0 and the provider
   interface refuses a non-allowlisted base URL while the cap is 0.

## Rejected alternatives

- **Claude via the subscription:** not permitted for third-party apps.
- **Paid API (Anthropic or OpenAI) with a small cap:** violates the $0 budget.
- **Gemini free tier as the main model:** closed weights, free-tier data may be used for training,
  and graded results could not be reproduced on HPRC.

## Consequences

- Groq's 8K tokens/min means development runs are throttled; the provider interface needs
  rate-limit-aware backoff (NFR-REL-3) and a smaller per-investigation token budget in `local` mode
  (proposed: 40,000 input tokens instead of 150,000).
- Groq's 200K tokens/day allows only a handful of full investigations a day, so full eval runs go to
  HPRC or local, and the public demo serves few live runs a day plus recorded replays.
- NFR-PERF-1 latency targets are measured on HPRC runs, not on the free tier.
- A 20B open model is weaker than frontier models. That makes the evaluation harness and the claim
  checker matter more, which suits the project's story; the single-vs-orchestrated study stays valid
  because both modes use the same model.
- Switching to a paid model later is a config change plus a new ADR for the budget.
