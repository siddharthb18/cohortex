# Cohortex — Engineering Requirements Specification (ERS)

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes. Exact pinned versions live in `docs/versions.md`.

## 1. Technology stack and version policy

Minimum versions are fixed here; exact versions are pinned once, in work package WP-00, to the latest stable release on that day, and recorded in `docs/versions.md`. Agents never upgrade a major version without a new ADR.

| Area | Choice | Minimum | Notes |
| --- | --- | --- | --- |
| Java runtime | Eclipse Temurin JDK | 21 LTS | Use 25 LTS if Spring Boot and all plugins support it on WP-00 day |
| Java framework | Spring Boot, Spring for Apache Kafka, Spring Data JDBC, springdoc-openapi | Latest stable Boot line | Build with Gradle (Kotlin DSL) |
| Python | CPython, managed with `uv` | 3.12 | One `uv` workspace for all Python packages |
| Agent framework | LangGraph | 1.x | Checkpointer backed by Postgres |
| MCP | Official MCP Python SDK | `mcp>=2.0,<3` | v2.0.0 shipped July 28, 2026 with 2026-07-28 spec support and built-in OpenTelemetry spans |
| MCP ↔ LangGraph bridge | `langchain-mcp-adapters` if it supports `mcp` 2.x; otherwise a thin in-repo adapter over the SDK's `Client` | — | WP-00 decides (see ADR-012) |
| API (Python) | FastAPI + Pydantic v2 | Latest stable | SSE via `sse-starlette` or native streaming |
| Analytics | DuckDB, Polars, SciPy, scikit-learn, XGBoost | DuckDB 1.x | DuckDB reads Parquet and, optionally, Iceberg |
| Database | PostgreSQL + pgvector | Postgres 16, pgvector 0.7 | Flyway owns migrations (run from the Java build) |
| Streaming | Apache Kafka in KRaft mode | 3.9 | No ZooKeeper; Redpanda acceptable locally if faster |
| Frontend | React + TypeScript + Vite; TanStack Query; a charting library such as Recharts | React 19, Node 22 LTS | Playwright for end-to-end tests |
| LLM providers | Zero cost only (ADR-013): open-weight gpt-oss-20b through any OpenAI-compatible server (Groq free tier, local Ollama, or vLLM on TAMU HPRC); no paid providers | — | Model IDs live in config, never in code |
| Embeddings | BAAI/bge-small-en-v1.5 (384-dim) run locally with fastembed (ADR-013) | — | Keeps indexing free and reproducible |
| Observability | OpenTelemetry SDKs + Collector; Jaeger or Langfuse for traces; Prometheus + Grafana | Latest stable | See section 4 |
| Packaging and deploy | Docker, Docker Compose, Kubernetes + Helm, Terraform | Compose v2, Helm 3 | One managed cloud only |
| CI | GitHub Actions | — | Required checks listed in section 3 |

## 2. Repository layout

One monorepo. Each component lives in its own directory with its own README, tests and Dockerfile; shared contracts live in `contracts/` and are the single source for generated types.

```text
cohortex/
├── CLAUDE.md                     # agent operating rules (build plan)
├── README.md                     # pitch, demo link, metrics, how it was built, attribution
├── Makefile                      # up, down, seed, test, eval, lint
├── docs/
│   ├── adr/                      # ADRs, NNN-title.md
│   ├── specs/                    # this spec set, exported to Markdown
│   ├── versions.md               # pinned versions (WP-00)
│   ├── open-questions.md         # anything the specs do not settle
│   └── failure-taxonomy.md       # from error analysis (human-owned)
├── contracts/
│   ├── openapi/fleet-api.yaml    # OpenAPI 3.1
│   ├── openapi/agent-service.yaml
│   ├── events/*.schema.json      # Kafka event JSON Schemas
│   ├── tools/*.schema.json       # MCP tool input/output schemas + manifest.json (hashes)
│   └── report/report.schema.json
├── services/
│   ├── fleet-api/                # Java, Gradle
│   ├── stream-ingest/            # Java, Gradle
│   ├── agent-service/            # Python
│   └── web-ui/                   # TypeScript
├── mcp/
│   ├── mcp-fleet/  mcp-stats/  mcp-docs/   # Python
├── pipelines/
│   ├── ingest-batch/             # Python + DuckDB
│   ├── analytics-worker/         # Python
│   └── corpus-indexer/           # Python
├── evals/
│   ├── golden/                   # v1/*.jsonl, versioned
│   ├── adversarial/
│   ├── harness/                  # runner, graders, judge, report
│   └── recordings/               # recorded LLM responses for CI
├── prompts/                      # versioned prompt files, one per node
├── db/migrations/                # Flyway SQL
├── data/fixtures/                # small attributed fixture subset only
├── deploy/
│   ├── compose/                  # docker-compose.yml, otel-collector.yaml
│   ├── helm/cohortex/
│   └── terraform/
└── .github/workflows/
```

## 3. Engineering standards

**Code style (enforced in CI, not by review)**

- Java: Spotless with google-java-format; Error Prone; no field injection; records for DTOs.
- Python: `ruff` (lint + format), `mypy --strict` on all packages; Pydantic models for every boundary.
- TypeScript: ESLint + Prettier; `strict: true`; types generated from `contracts/openapi`.

**Testing**

| Layer | Tooling | Rule |
| --- | --- | --- |
| Unit | JUnit 5, pytest, Vitest | Written before the implementation; every FR acceptance test has a named test |
| Integration | Testcontainers (Postgres, Kafka) | Real dependencies, no mocks of the database |
| Contract | OpenAPI validation; JSON Schema tests for events and tools | Generated clients must compile against the spec |
| Agent | pytest with recorded LLM responses | CI never calls a live model on pull requests; recordings are refreshed by a manual job |
| End-to-end | Playwright against Compose | One happy path per use case |
| Eval | `evals/harness` | Gate thresholds in the evaluation spec |

**CI pipeline (required checks on `main`)**

1. Lint and type-check all languages.
2. Unit and integration tests; coverage report.
3. Contract tests; schema hash check for MCP tool descriptions.
4. Build images; Trivy scan; gitleaks.
5. Eval gate on recorded responses.
6. Nightly only: live-model eval subset, k6 load test, recording refresh proposal.

**Workflow.** Trunk-based development; one pull request per work package or smaller; Conventional Commits; PR description lists FR IDs covered and pastes the eval delta. Squash-merge only after all required checks pass.

**Configuration and secrets.** Twelve-factor configuration through environment variables documented in `.env.example`. Secrets only in `.env` (git-ignored), GitHub Actions secrets, or Kubernetes secrets created by Terraform. Services fail fast on missing configuration.

**Security.** Tools are read-only (ADR-001); the corpus is fetched offline by `corpus-indexer`, never by the agent at runtime; tool output and documents are always wrapped as data in prompts, never concatenated into instructions; containers run as non-root with read-only filesystems where possible.

**LLM usage rules**

- All calls go through the provider interface (ADR-010) with timeouts, retries and token accounting.
- Prompts live in `prompts/<node>.<version>.md`; each run stores the prompt file hashes, model ID and temperature.
- Graded runs use temperature 0 and a pinned model ID.
- Structured outputs are validated with Pydantic; one repair attempt, then a typed failure.
- No user data beyond the question is sent to providers.

## 4. Observability conventions

One investigation is one trace, from the HTTP request through every model call, MCP tool call and fleet-api query. Span names and attributes follow the OpenTelemetry GenAI semantic conventions, which are still marked Development, so the pinned convention version is recorded in `docs/versions.md`.

**Span tree for one investigation**

```text
POST /v1/investigations                     (http server span, agent-service)
└─ invoke_agent cohortex.orchestrator       gen_ai.agent.name, cohortex.investigation.id, cohortex.mode
   ├─ chat {model}                          gen_ai.request.model, gen_ai.usage.input_tokens / output_tokens
   ├─ execute_tool fleet.cohort_afr         gen_ai.tool.name, cohortex.evidence.id
   │  └─ tools/call (mcp-fleet)              mcp.method.name, mcp.protocol.version  (emitted by MCP SDK 2.x)
   │     └─ GET /v1/cohorts/...  (fleet-api) http.route, db spans
   └─ cohortex.evidence_check               cohortex.claims.total, cohortex.claims.unsupported
```

**Custom attributes** use the `cohortex.` prefix: `investigation.id`, `mode`, `evidence.id`, `prompt.hash`, `eval.run_id` (eval runs only).

**Metrics (Prometheus names)**

| Metric | Type | Labels |
| --- | --- | --- |
| `cohortex_investigation_duration_seconds` | Histogram | mode, status |
| `cohortex_investigation_cost_usd` | Histogram | mode, model |
| `cohortex_llm_tokens_total` | Counter | direction (input or output), model, node |
| `cohortex_tool_calls_total` | Counter | tool, outcome |
| `cohortex_claims_unsupported_total` | Counter | mode |
| `cohortex_ingest_rows_total` | Counter | source, table |
| `cohortex_replay_consumer_lag` | Gauge | topic, partition |

**Logs** are JSON lines with `timestamp`, `level`, `service`, `trace_id`, `span_id`, `message` and event fields; never full prompts at INFO level. Prompt and completion content is captured only in the trace backend, and only when `COHORTEX_CAPTURE_CONTENT=true`.

**Dashboards** (Grafana JSON in `deploy/`): investigations (rate, latency, cost, unsupported claims), tools (calls, errors, latency by tool), ingest (rows, lag), and eval trends.

## 5. Budgets and environment variables

Budgets are enforced in code or CI, not just documented; the SRS non-functional table holds the targets, and this section says where each is enforced.

| Budget | Limit | Enforced in |
| --- | --- | --- |
| Tool calls per investigation | 20 | `agent-service` graph guard |
| Input tokens per investigation | 150,000 | Provider interface token counter |
| Wall time per investigation | 180 s | Async timeout around the graph |
| Tool result size | 4 KB serialized | MCP server response middleware |
| Monthly LLM spend (demo) | $0: only free-tier or local endpoints are configured (ADR-013) | Provider interface allowlist + spend ledger |
| Public demo rate | 5 investigations per IP per day | `agent-service` rate limiter |
| CI live-model spend | $0: nightly subset on free tiers or HPRC only | Workflow config + spend ledger |

**Core environment variables** (all listed with defaults in `.env.example`)

| Variable | Used by | Purpose |
| --- | --- | --- |
| `COHORTEX_ENV` | All | `local`, `ci` or `demo` |
| `DATABASE_URL` | Java and Python services | Postgres connection |
| `KAFKA_BOOTSTRAP_SERVERS` | stream-ingest, analytics-worker | Kafka brokers |
| `RAW_DATA_URI` | ingest-batch, eval-harness | Local path or object-store URI of the raw layer |
| `COHORTEX_WINDOW_QUARTERS` | ingest-batch | Backblaze quarters loaded into serving tables; default 6 |
| `FLEET_API_URL` | mcp-fleet, web-ui | Fleet API base URL |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | agent-service | Provider, OpenAI-compatible endpoint, pinned model ID, key |
| `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY` | eval-harness judge | Judge endpoint and model (different family from the agent) |
| `EMBEDDING_MODEL` | corpus-indexer, mcp-docs | Embedding model ID; EMBEDDING_DIM must equal its vector size (feeds the Flyway placeholder) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | All | Collector endpoint |
| `COHORTEX_CAPTURE_CONTENT` | agent-service | Store prompt content in traces; default false |
| `COHORTEX_MONTHLY_LLM_CAP_USD` | agent-service | Spend cap; default 0 |
| `ADMIN_TOKEN` | agent-service, web-ui | Owner mode in the demo |
