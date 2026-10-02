# Architecture decision records

Each ADR starts as **Proposed**. Siddharth accepts or rejects it by changing its status line to
`Accepted` or `Rejected` (with a one-line reason) before the work package that depends on it begins.
Agents never change an ADR's status or content; a changed decision is a new ADR that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [001](001-model-never-writes-sql.md) | The model never writes SQL; it calls typed, parameterized, read-only tools | Proposed |
| [002](002-mcp-tools-call-fleet-api.md) | MCP data tools call `fleet-api`, never the database | Proposed |
| [003](003-postgres-pgvector-serving-store.md) | Postgres + pgvector holds serving data and corpus vectors | Proposed |
| [004](004-raw-layer-is-eval-truth.md) | Parquet + DuckDB raw layer is the eval truth source | Proposed |
| [005](005-kafka-for-replay-only.md) | Kafka carries replay events and alerts only; backfill uses bulk `COPY` | Proposed |
| [006](006-langgraph-for-both-modes.md) | LangGraph orchestrates both agent modes behind one interface | Proposed |
| [007](007-afr-exact-poisson-ci.md) | AFR uses Backblaze's formula with exact Poisson 95% intervals | Proposed |
| [008](008-claims-carry-evidence.md) | Every claim carries `evidence_ids`; numbers are checked by code before any LLM check | Proposed |
| [009](009-otel-genai-tracing.md) | Tracing follows OpenTelemetry GenAI semantic conventions | Proposed |
| [010](010-single-llm-provider-interface.md) | Model access goes through one provider interface configured by environment | Proposed |
| [011](011-java-platform-python-ai.md) | Java for ingest streaming and the fleet API; Python for analytics, tools, agent and evals | Proposed |
| [012](012-in-repo-mcp-adapter.md) | Bridge MCP tools into LangGraph with a thin in-repo adapter over the MCP SDK 2.x client | Proposed |
