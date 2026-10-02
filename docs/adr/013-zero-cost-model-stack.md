# ADR-013: Zero-cost model stack: open-weight models behind OpenAI-compatible endpoints

- **Status:** Accepted
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
| Kaggle notebooks | Free NVIDIA T4 or P100 GPUs; Ollama or vLLM can run `gpt-oss-20b` inside the notebook | About 30 GPU hours a week, phone verification, sessions end after a few hours |
| OpenRouter free models | Several free models behind one OpenAI-compatible API | 20 req/min, 200 req/day; `gpt-oss-20b` not on the free list at check time |
| Google Gemini free tier | Strong closed models | Free-tier prompts may be used for training; closed weights hurt reproducibility |
| Cerebras, GitHub Models | — | Cerebras is a trial only; GitHub Models was retired on 2026-07-30 |

## Decision

1. The agent model is **`gpt-oss-20b`** (open weights, Apache-2.0), reached only through an
   OpenAI-compatible endpoint. The same weights run in three places:
   - **Development:** Groq free tier (`openai/gpt-oss-20b`).
   - **Offline development:** local Ollama (`gpt-oss:20b`).
   - **Graded eval runs and the experiment (WP-18):** local Ollama on the dev PC when its GPU or
     RAM can hold the model; otherwise the eval harness runs inside a free Kaggle GPU notebook
     against Ollama there. Either way the weights are the same, so results are reproducible and
     not limited by free-tier token quotas. TAMU HPRC is **not** used (Siddharth's decision, 2026-10-02).
2. The **judge** uses a different model family from the agent, to reduce self-preference:
   `qwen/qwen3.8-27b` on Groq (judge calls are short, so the free tier covers them).
3. **Embeddings** use `BAAI/bge-small-en-v1.5` (384 dimensions) run locally with `fastembed`; no API.
4. **CI** uses recorded responses only (already in ERS); the optional nightly live subset runs only
   against the Groq free tier.
5. The provider interface (ADR-010) is implemented with the `openai` Python SDK against
   `LLM_BASE_URL`. No paid provider is configured; the spend cap defaults to 0 and the provider
   interface refuses a non-allowlisted base URL while the cap is 0.

## Rejected alternatives

- **Claude via the subscription:** not permitted for third-party apps.
- **Paid API (Anthropic or OpenAI) with a small cap:** violates the $0 budget.
- **Gemini free tier as the main model:** closed weights, free-tier data may be used for training,
  and graded results could not be reproduced locally.
- **TAMU HPRC GPUs:** ruled out by Siddharth.

## Consequences

- Groq's 8K tokens/min means development runs are throttled; the provider interface needs
  rate-limit-aware backoff (NFR-REL-3) and a smaller per-investigation token budget in `local` mode
  (proposed: 40,000 input tokens instead of 150,000).
- Groq's 200K tokens/day allows only a handful of full investigations a day, so full eval runs go to
  the local PC or a Kaggle notebook, and the public demo serves few live runs a day plus recorded replays.
- NFR-PERF-1 latency targets are measured on the Groq free tier (fast, but throttled); local and
  Kaggle runs are graded for correctness, not latency.
- WP-19 (inference memory profiling) runs on the local GPU or a Kaggle T4 instead of HPRC.
- A 20B open model is weaker than frontier models. That makes the evaluation harness and the claim
  checker matter more, which suits the project's story; the single-vs-orchestrated study stays valid
  because both modes use the same model.
- Switching to a paid model later is a config change plus a new ADR for the budget.
