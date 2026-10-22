# Pinned versions

Pinned in WP-00 on **2026-10-02** to the latest stable release on that day, per ERS §1.
Agents never upgrade a **major** version without a new ADR. Minor and patch upgrades go
through a normal PR with the eval gate green. Every new dependency is added here with a one-line reason.

Python packages are added to a component's `pyproject.toml` only in the work package that needs
them, at the version listed here; `uv.lock` is the authoritative lock.

## Runtimes and build tools

| Tool | Version | Reason / note |
| --- | --- | --- |
| Eclipse Temurin JDK | 25 LTS (25.0.4.1 at pin time) | ERS allows 25 when Spring Boot and plugins support it; Spring Boot 4.1 and Gradle 9.8 do. Fallback: 21 LTS if any plugin breaks (record it here) |
| Gradle (wrapper) | 9.8.0 | Kotlin DSL; toolchains resolve JDK 25 via the foojay resolver |
| CPython | 3.13 | Above the ERS minimum (3.12); every pinned Python dependency ships 3.13 wheels. 3.14 deferred until all wheels are confirmed |
| uv | 0.12.x | Workspace manager; lockfile `uv.lock` |
| Node.js | 22 LTS | For `web-ui` (WP-08) and tooling |

## Java libraries and plugins (WP-02, WP-04, WP-13)

| Artifact | Version | Note |
| --- | --- | --- |
| Spring Boot | 4.1.1 | Latest stable line (4.2 is at milestone 2). Manages Spring Kafka, Spring Data JDBC, Flyway, Jackson, JUnit versions via its BOM |
| springdoc-openapi | 3.1.1 | 3.x line targets Spring Boot 4 |
| Flyway | managed by Spring Boot BOM | Latest upstream is 13.9.0; do not override the BOM without a reason |
| Testcontainers | 2.0.5 | Postgres and Kafka modules |
| Spotless Gradle plugin | 8.10.3 | With its default google-java-format (pinning 1.37.0 broke the in-process call) |
| Error Prone | 2.50.0 | Via `net.ltgt.errorprone` plugin 5.1.1 |
| foojay toolchain resolver | 1.0.0 | `org.gradle.toolchains.foojay-resolver-convention` |

## Python packages

| Package | Version | First used in |
| --- | --- | --- |
| mcp | 2.2.0 | WP-05 (servers), WP-06 (client). Requires protocol 2026-07-28 support (v2 line) |
| langgraph | 1.2.12 | WP-06 |
| langchain-core | 1.6.6 | WP-06 (LangGraph message types only) |
| langchain-mcp-adapters | **not used** | 0.3.2 requires `mcp<2.0.0`; see ADR-012 |
| openai | 3.24.0 | WP-06, client for every OpenAI-compatible endpoint behind the provider interface (ADR-010, ADR-013) |
| anthropic | **not used** | $0 budget; subscriptions cannot power third-party apps (ADR-013) |
| fastembed | 0.8.1 | WP-10, local ONNX embeddings for `BAAI/bge-small-en-v1.5` (ADR-013) |
| fastapi | 0.142.2 | WP-06 |
| pydantic | 2.13.5 | All Python boundaries |
| uvicorn | 0.54.0 | WP-06 |
| sse-starlette | 3.5.0 | WP-06 |
| httpx | 0.28.1 | WP-05 (fleet-api client), tests |
| duckdb | 1.5.6 | WP-03, WP-07 |
| pyarrow | 25.0.1 | WP-03 |
| polars | 1.44.2 | WP-03, WP-14 |
| scipy | 1.18.1 | WP-05 (stats tools), WP-14 |
| scikit-learn | 1.9.1 | WP-14 |
| xgboost | 3.4.1 | WP-14 |
| psycopg[binary] | 3.3.6 | WP-03, WP-06 |
| jsonschema | 4.26.0 | Contract tests |
| python-ulid | 4.0.1 | WP-13 (event IDs) |
| opentelemetry-sdk / -exporter-otlp | 1.45.0 | WP-12 |
| ruff | 0.16.10 | Dev, WP-00 |
| mypy | 2.4.0 | Dev, WP-00 |
| pytest | 9.1.1 | Dev, WP-00 |
| pytest-asyncio | 1.4.0 | Dev, WP-05 onward |
| cohortex-mcp-common | 0.1.0 (workspace package) | WP-05: shared MCP plumbing (contracts, hash check, validation, envelope, 4 KB paging) |

## Frontend (pinned in WP-08; observed latest on 2026-10-02)

react 19.3.0, vite 8.3.2, typescript 7.0.2, @tanstack/react-query 5.104.1, recharts 3.10.1,
@playwright/test 1.63.0, vitest 5.0.3, eslint 10.11.0, prettier 3.9.9.
TypeScript 7 is the native-compiler release; WP-08 confirms the Vite and ESLint toolchain accepts it, else pins 5.9.

## Models and model servers ($0, ADR-013)

| Item | Version / ID | Note |
| --- | --- | --- |
| Agent model | `gpt-oss-20b` (Groq `openai/gpt-oss-20b`, Ollama `gpt-oss:20b`) | Open weights, Apache-2.0 |
| Judge model | `qwen/qwen3.8-27b` | Different family from the agent |
| Embedding model | `BAAI/bge-small-en-v1.5`, 384-dim | Local via fastembed |
| Local model (Ollama) | `qwen3:1.7b` (1.4 GB; fallback `qwen3:4b`) | Siddharth asked for an extremely lightweight local model (PC: 32 GB RAM, CPU); tool calling supported |
| Ollama | 0.35.x | Optional local server on the dev PC |
| vLLM | 0.30.0 | Optional, inside Kaggle notebooks for WP-19; not a workspace dependency |

## Infrastructure images (Docker Compose)

| Image | Tag | Note |
| --- | --- | --- |
| pgvector/pgvector | 0.8.7-pg18 | PostgreSQL 18 (18.6 latest; 19 is in beta) with pgvector 0.8.7. Verify the tag on first `make up` |
| apache/kafka | 4.3.1 | KRaft only (4.x removed ZooKeeper); 4.4.0 is at RC |
| otel/opentelemetry-collector-contrib | 0.162.0 | |
| jaegertracing/jaeger | 2.21.0 | Jaeger v2 accepts OTLP directly |

## GitHub Actions

actions/checkout v7, actions/setup-java v6, astral-sh/setup-uv v7, gradle/actions v6,
actions/setup-node v7, gitleaks/gitleaks-action v3 (v3 may require a license key for organization
accounts; personal repos are free), docker/setup-compose-action v2.

## Standards

| Standard | Version |
| --- | --- |
| MCP protocol | 2026-07-28 |
| OpenTelemetry GenAI semantic conventions | Pin in WP-12 (still "Development" status) |
| OpenAPI | 3.1 |
