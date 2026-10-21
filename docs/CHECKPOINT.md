# Checkpoint — 2026-10-21 (resume here)

**Start a new session with:** "Resume Cohortex from docs/CHECKPOINT.md in C:\Users\aftri\Documents\finalProject."

## Done (on `main`, synced to the PC)
- WP-00 bootstrap; all ADRs 001–013 Accepted ($0 stack: gpt-oss-20b via Groq free tier / local Ollama / Kaggle; no TAMU HPRC).
- `docs/implementation-notes.md`: binding integration contract (ports, DB, raw layer, AFR math, API/SSE shapes).
- `contracts/rawlayer/views.sql`, `contracts/fixtures/afr_ci_cases.json`, `contracts/tools/*` (schemas + manifest).
- WP-05 MCP servers: `mcp/mcp-common`, `mcp/mcp-stats`, `mcp/mcp-fleet` (141 tests).
- WP-07 eval harness `evals/harness` + 30 draft golden cases (`reviewed_by: null`) + adversarial suite.
- `deploy/docker/python.Dockerfile`, `.dockerignore`. Full Python suite: 223 passing.

## In progress when paused (built in the cloud workspace; may be LOST if that workspace expired)
- WP-01/02/03 data layer (`db/migrations/V1__init.sql`, `pipelines/ingest-batch`, synthetic fixture)
- WP-04 fleet-api (Java, Spring Boot 4.1.1) — could not compile: Maven Central blocked
- WP-06/11 agent-service (single + orchestrated LangGraph, provider, ledger, checker, SSE)
- WP-08 web-ui (React; Investigate/Fleet/Cohort/Alerts/Evals; static demo mode for GitHub Pages)
If those branches aren't on `main`, rebuild each with the prompts' scope from `docs/specs/build-plan.md` + `docs/implementation-notes.md`.

## Next steps for Claude
1. Merge remaining branches (rebase onto main, re-author as Claude <noreply@anthropic.com>, regenerate `uv.lock`).
2. Integrate: Compose services (fleet-api 8080, agent 8000, mcp-fleet 8101, mcp-stats 8102, web-ui 5173),
   Makefile targets (`seed`, `backfill`, `mcp-fleet`, `mcp-stats`, `manifest-check`, `truth`, `eval`, `eval-gate`),
   CI jobs (Postgres service, manifest-check, eval gate on recordings, GitHub Pages demo).
3. Add open-question rows for new defaults; README rewrite with screenshots + resume bullets.
4. Sync to PC with a NEW bundle filename each time (device_commit_files reuses old content for same name).

## Environment notes
- Cloud workspace blocks Maven/Gradle/Backblaze/Groq/HF/Docker Hub; PyPI, npm, GitHub (git), Ubuntu apt work.
  Local Postgres 16 + pgvector built from source for tests (`initdb` as `postgres` user, trust auth).
- PC folder is reached through the device bridge; git there needs delete permission (request once per session).

## Siddharth's actions (outstanding)
1. Add allowed domains in claude.ai Settings → Capabilities: repo.maven.apache.org, plugins.gradle.org,
   services.gradle.org, api.foojay.io, api.adoptium.net, github.com, objects.githubusercontent.com,
   release-assets.githubusercontent.com, f001.backblazeb2.com, www.backblaze.com, api.groq.com,
   huggingface.co, cdn-lfs.hf.co, cas-bridge.xethub.hf.co.
2. Sign in at console.groq.com (GitHub/Google) so Claude can create the API keys for `.env`.
3. Tell Claude the PC's RAM and GPU (decides local Ollama vs Kaggle for graded runs).
4. Later: review the 30 golden cases (`evals/golden/v1/README.md`), confirm open questions 14–25,
   create a GitHub repo for publishing, Tianchi login for Alibaba data.
