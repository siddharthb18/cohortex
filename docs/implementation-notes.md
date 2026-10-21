# Implementation notes (integration contract for Phase 1)

The specs in `docs/specs/` leave some details open. This file fixes them so every component agrees.
Each decision here is also listed in `docs/open-questions.md` (items 14+) for Siddharth to confirm or
change; until he does, this file is binding for agents.

## 1. Processes, ports and URLs (local)

| Component | Port | Base URL env var (for callers) |
| --- | --- | --- |
| Postgres + pgvector | 5432 | `DATABASE_URL` |
| fleet-api (Java) | 8080 | `FLEET_API_URL=http://localhost:8080` |
| agent-service (FastAPI) | 8000 | `AGENT_API_URL=http://localhost:8000` |
| mcp-fleet (streamable HTTP at `/mcp`) | 8101 | `MCP_FLEET_URL=http://localhost:8101/mcp` |
| mcp-stats (streamable HTTP at `/mcp`) | 8102 | `MCP_STATS_URL=http://localhost:8102/mcp` |
| mcp-docs (Phase 2) | 8103 | `MCP_DOCS_URL=http://localhost:8103/mcp` |
| web-ui (Vite dev / nginx) | 5173 | proxies `/api/agent` → 8000 and `/api/fleet` → 8080 |

Every MCP server also runs over stdio (`python -m cohortex_mcp_<name> --stdio`) for MCP Inspector.

## 2. Database

- Flyway migration `db/migrations/V1__init.sql` is the DDL in contracts §2, verbatim, with
  `${embedding_dim}` as the only placeholder. fleet-api runs Flyway on startup (`spring.flyway.locations`
  points at the repo's `db/migrations`, copied into the image).
- Python code and tests apply the same file with `${embedding_dim}` replaced by `EMBEDDING_DIM` (384)
  when the `flyway_schema_history` table is absent (helper: read the file, replace the placeholder,
  execute in one transaction). Python never owns later migrations.
- Python tests use `COHORTEX_TEST_DATABASE_URL` (default `postgresql://cohortex@localhost:5432/cohortex`).
  Each test session creates a fresh database named `cohortex_test_<package>_<random>`, applies V1, and
  drops it at the end. CI provides Postgres with pgvector as a service container.
- `smart_daily` monthly partitions are named `smart_daily_yYYYYmMM` and created by ingest before loading.

## 3. Raw layer and serving derivations (ingest-batch)

- Raw-layer layout and DuckDB views: `contracts/rawlayer/views.sql` (shared with the eval harness).
- Backblaze known non-SMART columns: `date, serial_number, model, capacity_bytes, failure, datacenter,
  cluster_id, vault_id, pod_id, pod_slot_num, is_legacy_format`. Any other column not matching
  `smart_\d+_(normalized|raw)` fails the run naming the column (FR-ING-3).
- `schema_version` = first 12 hex chars of SHA-256 of the day file's lower-cased header line.
- Media: Backblaze rows are `hdd`, Alibaba rows `ssd` (open question 14 covers Backblaze boot SSDs).
- `drive_model.capacity_bytes` = the most common positive `capacity_bytes` for that model; NULL for Alibaba.
- `drive`: `first_seen` = min day, `last_seen` = max day, `failed_on` = the day with `failure = 1`.
  Alibaba `drive_id` = `model || ':' || disk_id`; Alibaba `failed_on` per `contracts/rawlayer/views.sql`.
- `drive.sampled` (the 1% hash sample): `int(md5(drive_id).hexdigest()[:8], 16) % 100 == 0`, where
  `drive_id` is the source's drive ID string. Same rule in every language.
- `smart_daily` holds the kept attributes (contracts §1) for (a) sampled drives on every observed day and
  (b) failed drives on the 60 days up to and including `failed_on`. Backblaze `raw_value` =
  `smart_{id}_raw`, `normalized` = `smart_{id}_normalized`; Alibaba `raw_value` = `r_{id}`,
  `normalized` = `n_{id}`.
- `cohort_daily`: per model and day, `drive_count` = rows, `failures` = sum of `failure`.
- Idempotency (FR-ING-4): one transaction per quarter; delete that source's `cohort_daily` and
  `smart_daily` rows for the quarter's days, re-insert, and upsert `drive` with
  `first_seen = least(...)`, `last_seen = greatest(...)`, `failed_on = coalesce(new, old)`.
- Reconciliation (FR-ING-5): per model, drive-days and failures from `drive_day` (raw) must equal sums of
  `cohort_daily` (serving) for the quarter. Result JSON stored in `ingest_run.reconciliation`:
  `{"ok": bool, "models": [{"model", "raw_drive_days", "serving_drive_days", "raw_failures", "serving_failures"}]}`.
- Periods: quarter label `YYYYQn` (e.g. `2026Q2`), month label `YYYY-MM`.

## 4. AFR and statistics (identical in Java and Python, FR-ANA-1)

- `afr_pct = failures * 365 * 100 / drive_days`.
- Exact Poisson interval, `a = (1 - confidence) / 2`: lower count = `chi2.ppf(a, 2k) / 2` (0 when k = 0),
  upper count = `chi2.ppf(1 - a, 2k + 2) / 2`; each converted with the same factor as AFR.
  Cross-language fixture: `contracts/fixtures/afr_ci_cases.json` (1,000 cases, tolerance 1e-9 relative).
- `compare_rates`: exact conditional binomial test. Given `k = ka + kb`, under H0 `ka ~ Binomial(k, p0)`
  with `p0 = dda / (dda + ddb)`; two-sided p-value as `scipy.stats.binomtest`; `rate_ratio =
  (ka/dda)/(kb/ddb)`; CI from the Clopper-Pearson interval on `p` mapped by `p/(1-p) * ddb/dda`.
- `change_point`: single change point in a Poisson rate series; statistic = max log-likelihood ratio over
  split points; p-value by parametric bootstrap under H0 (999 draws, fixed seed 7) so it is deterministic.

## 5. fleet-api semantics

- `GET /v1/models` `drive_count` = the model's `drive_count` on its latest day in `cohort_daily`.
- Cohort windows are `[from, to]` inclusive. A window whose quarters from `quarter(from)` to
  `quarter(to)` number more than 8, or with `to < from`, is rejected with 400 problem details (FR-API-8).
- `compare`: a model qualifies when its `drive_count` on its last day inside the window ≥ `min_drives`.
  `rate_ratio_vs_fleet` = model AFR ÷ AFR of all models of that source in the window. Ranked by `afr_pct`
  descending, ties by model ascending. `limit` default 20, max 50.
- `fleet/summary` `drives` = distinct drives with `first_seen ≤ to` and `last_seen ≥ from`.
- `smart-trend`: sampled drives only (`drive.sampled`), p50/p95 by `percentile_cont` over `raw_value`,
  `nonzero_share` = share of drive-days with `raw_value > 0`, `n_drives` = distinct sampled drives.
- `failed-drives`: `age_days = failed_on - first_seen`; `last_smart` = `{attr: raw_value}` on `failed_on`.
- Pagination: `page` (0-based, default 0), `size` (default 100, max 500). Paged responses are
  `{"items": [...], "page", "size", "total"}`.
- Every AFR-bearing response includes `"method": "exact_poisson_95"` and `"generated_at"`.

## 6. MCP tools

- MCP tool names are the bare names in contracts §5 (`cohort_afr`); the envelope `tool` field is
  `<server>.<name>` (`fleet.cohort_afr`); the name shown to the LLM is `<server>_<name>`
  (`fleet_cohort_afr`) because OpenAI-style function names cannot contain dots.
- Input JSON Schemas: `contracts/tools/<server>.<name>.input.schema.json`; the envelope schema:
  `contracts/tools/envelope.schema.json`; descriptions and their SHA-256 in `contracts/tools/manifest.json`.
- Tool errors are returned as MCP tool results with `isError: true` and a JSON body
  `{"error": {"code": "invalid_argument" | "not_found" | "upstream_error" | "too_large", "message": "..."}}`,
  never a stack trace.
- Result size cap 4 KB serialized (FR-TOOL-6): list results are cut to fit, `truncated: true`, and
  `next_page` set to the next page number.

## 7. agent-service API details

- `POST /v1/investigations` body `{question, scope?, mode?}` → `202 {"id", "status": "queued"}`.
- `GET /v1/investigations/{id}` → `{"id", "question", "scope", "mode", "status", "llm_model",
  "started_at", "finished_at", "tokens_in", "tokens_out", "cost_usd", "report", "markdown"}`
  (`report`/`markdown` null until finished).
- `GET /v1/investigations/{id}/events` (SSE). Replays stored steps first, then live ones.
  - `event: step`, `data: {"seq", "node", "kind", "payload", "started_at", "ended_at"}`.
    Payloads: `plan` → `{"plan": Plan}`; `tool_call` → `{"tool", "args", "evidence_id", "ok",
    "summary"}`; `draft` → `{"claims": [Claim]}`; `check` → `{"supported", "unsupported", "notes": [str]}`;
    `report` → `{"status"}`; `error` → `{"message"}`.
  - Terminal `event: report`, `data: {"status", "report", "markdown"}` or `event: error`,
    `data: {"status", "message"}`; then the stream closes.
- `GET /v1/investigations/{id}/evidence/{evidence_id}` → `{"evidence_id", "tool", "args", "result",
  "created_at"}` where `result` is the full envelope.
- `GET /v1/investigations?limit=20` (extension, open question 18): recent investigations, newest first.
- `GET /v1/evals/latest?mode=` → latest `eval_run` row as JSON, or 404.
- LLM settings: `COHORTEX_LLM_MODE` = `live` | `record` | `replay` (default `live`);
  `COHORTEX_RECORDINGS_DIR` (default `evals/recordings`). Replay keys requests by SHA-256 of the
  canonical JSON of `{model, messages, tools, response_format, temperature}`.
- Budgets: `COHORTEX_MAX_TOOL_CALLS` (20), `COHORTEX_MAX_INPUT_TOKENS` (150000), `COHORTEX_MAX_SECONDS` (180).
- Paid endpoints are refused while `COHORTEX_MONTHLY_LLM_CAP_USD` is 0: the provider only accepts
  `LLM_BASE_URL` hosts in `api.groq.com`, `localhost`, `127.0.0.1`, `host.docker.internal`, `ollama`,
  plus any host in `COHORTEX_FREE_LLM_HOSTS` (comma-separated). Cost is recorded as 0.

## 8. Eval harness

- Golden cases: `evals/golden/v1/cases.jsonl` in the evaluation-spec format. Drafted cases have
  `"reviewed_by": null` and are excluded from the gate until Siddharth reviews them.
- `numeric_primary` reads the first `NumberRef` in the report's summary, then findings, whose unit equals
  the case's `primary_answer.unit` and whose `field` ends with `primary_answer.field`.
- Gate thresholds: evaluation spec §1, stored in `evals/harness/thresholds.json`; baseline in
  `evals/baselines/v1.json`. With zero reviewed cases the gate reports `skipped` and exits 0.
