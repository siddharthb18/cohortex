# Cohortex — Design Document

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes. The architecture diagram lives only in the doc.

## 1. Goals and non-goals

Cohortex lets a reliability engineer ask "why did this drive cohort's failure rate change?" and get a cited report whose every number can be re-derived from public data. It is a portfolio system built to production standards, not a product for real fleets.

**Goals**

| ID | Goal | Measured by |
| --- | --- | --- |
| G1 | Investigate cohort reliability questions end to end: plan, gather evidence through tools, write a cited report | Investigation completion rate on the golden set |
| G2 | Make every numeric claim verifiable | Numeric-claim accuracy against independent SQL; share of claims with evidence links |
| G3 | Run like a production service: streaming ingest, typed APIs, tracing, deployable to Kubernetes | SRS non-functional requirements met in the demo environment |
| G4 | Measure quality continuously and block regressions | CI eval gate active on every pull request |
| G5 | Answer an architecture question with data: one agent versus orchestrator-workers | Published comparison of accuracy, latency and cost |

**Non-goals**

- Predicting failures for any real fleet, or giving purchasing advice.
- Letting the model write SQL or reach the database directly.
- Fine-tuning or training language models.
- Multi-tenant accounts. The demo is single-user, plus a rate-limited public read-only mode.
- Vendor firmware or NAND-level analysis; the data does not support it.

## 2. Architecture

Twelve components in four layers: data, platform services, agent tools, and the agent with its UI and evals. Java owns the platform services; Python owns analytics, tools, the agent and evals. The model reaches data only through MCP tools, and the eval harness checks it against a separate copy of the data.

*(Diagram in the doc.)* Read top to bottom: data flows into the raw layer and the serving store; the agent reaches data only through MCP tools and the fleet API, while the eval harness computes truth from the raw layer alone.

| ID | Component | Stack | Responsibility | Depends on |
| --- | --- | --- | --- | --- |
| C1 | `ingest-batch` | Python, DuckDB | Download Backblaze and Alibaba data; convert CSV to partitioned Parquet (raw layer); bulk-load serving tables with `COPY` | Raw layer, Postgres |
| C2 | `stream-ingest` | Java 21+, Spring Boot, Spring for Apache Kafka | Replay producer emits daily snapshot events on an accelerated clock; consumer updates drive lifecycle and cohort counts; emits a day-closed event | Kafka, Postgres |
| C3 | `fleet-api` | Java, Spring Boot, Spring Data JDBC, springdoc-openapi | Read-only REST API: models, cohorts, AFR, SMART trends, failed drives, alerts | Postgres |
| C4 | `analytics-worker` | Python, Polars, SciPy, XGBoost | On day-closed: refresh cohort windows, run change detection, score drive risk, publish alerts | Kafka, Postgres |
| C5 | `mcp-fleet` | Python, MCP SDK 2.x | Typed read-only fleet tools; wraps `fleet-api` | C3 |
| C6 | `mcp-stats` | Python, MCP SDK 2.x, SciPy | Pure statistics tools: AFR confidence intervals, rate comparison, change points | None |
| C7 | `mcp-docs` | Python, MCP SDK 2.x | Hybrid search and passage fetch over the reliability corpus | Postgres (pgvector, full-text) |
| C8 | `corpus-indexer` | Python | Load open-access papers and Backblaze reports, chunk, embed, index | Postgres |
| C9 | `agent-service` | Python, FastAPI, LangGraph | Investigation API in two modes (single agent, orchestrated); evidence ledger; live step stream over SSE | C5–C7, LLM provider, Postgres |
| C10 | `web-ui` | React, TypeScript, Vite | Fleet dashboard, alert inbox, live investigation view, report with evidence drawer | C3, C9 |
| C11 | `eval-harness` | Python | Golden sets, truth SQL on DuckDB over the raw layer, graders, judge, reports, CI gate | C9, raw layer |
| C12 | `platform` | Docker Compose, Kubernetes + Helm, Terraform, GitHub Actions, OpenTelemetry Collector, Jaeger or Langfuse, Prometheus, Grafana | Build, deploy, observe | All |

## 3. Data architecture

Data lives in two independent layers. The raw layer keeps every source row in Parquet and is queried only by DuckDB; the serving layer keeps small, query-shaped tables in Postgres for the APIs and the agent. Because eval truth comes from the raw layer and the agent's numbers come from the serving layer, a grading pass is a genuine cross-check, not the system grading itself.

**Raw layer (Parquet, DuckDB)**

- Backblaze: one Parquet file per day under `data/raw/backblaze/year=YYYY/quarter=Qn/`, converted from the daily `YYYY-MM-DD.csv` files in each quarterly ZIP. All columns kept, names lower-cased, schema version recorded per file because Backblaze changes the schema between quarters.
- Alibaba SSD: daily SMART files and the failure-label file converted to `data/raw/alibaba/`.
- Optional: query Backblaze's public Apache Iceberg copy of Drive Stats with DuckDB instead of downloading ZIPs (credentials from the Drive Stats page, kept in `.env`).

**Serving layer (Postgres 16+ with pgvector)**

| Table | Grain | Approximate size per Backblaze quarter |
| --- | --- | --- |
| `drive_model` | One row per source + model | About 100 rows total |
| `drive` | One row per drive serial: first seen, last seen, failed on | About 350,000 |
| `cohort_daily` | Model × day: drive count, failures | About 9,000 |
| `smart_daily` | Drive × day, selected SMART attributes only, for failed drives (60 days before failure) and a fixed 1% hash sample of healthy drives | About 400,000 |
| Alerts, investigations, steps, claims, evidence, corpus chunks, eval runs | Application data | Small |

The default demo window is the last six Backblaze quarters plus the full Alibaba 2018–2019 period, set by `COHORTEX_WINDOW_QUARTERS`. Exact DDL is in the contracts file.

**Core definitions**

- A **drive-day** is one drive observed on one day. A **cohort** is a set of drives sharing a source and model, optionally narrowed by capacity or data center.
- A drive's `failure` flag is 1 on its last operational day before failure, as Backblaze records it.
- AFR follows Backblaze's convention, with an exact Poisson 95% interval (ADR-007):

```latex
\mathrm{AFR} = \frac{\text{failures}}{\text{drive-days} / 365} \times 100\%
```

**Streaming (Kafka, KRaft mode)**

Replay mode turns historical days into a live feed. For each simulated day the producer emits one `cohort.day.v1` event per model, one `drive.failure.v1` per failure, and `drive.snapshot.v1` for sampled drives, then `fleet.day.closed.v1`. The default clock is one simulated day per 30 seconds.

## 4. Key flows

**A. Backfill** (`ingest-batch`, run once per new quarter)

1. Download the quarter's ZIP; verify size and checksum; record the source URL and download time in `ingest_run`.
2. Read the current Backblaze schema file; fail loudly on unknown non-SMART columns.
3. Convert each daily CSV to Parquet in the raw layer.
4. With DuckDB, derive `drive`, `cohort_daily` and the sampled `smart_daily` rows; `COPY` them into Postgres inside one transaction per quarter.
5. Run row-count reconciliation: drive-days and failures per model must match between raw and serving layers exactly. Mismatch fails the run.

**B. Replay and alert**

1. `stream-ingest` reads raw days after the backfilled window and emits the events defined in the contracts file.
2. Its consumer upserts `drive` and `cohort_daily`, then emits `fleet.day.closed.v1`.
3. `analytics-worker` recomputes 30- and 90-day cohort AFR, runs change detection (rate-ratio test against the prior 90 days, minimum 60 drives and 3 failures), and writes an `alert` when p < 0.01 and the ratio exceeds 1.5.
4. It publishes `alerts.cohort.v1`; the UI shows the alert with an "Investigate" button.

**C. Investigation (orchestrated mode)**

1. `POST /investigations` with a question, optional cohort scope and mode; the service returns an ID and streams steps over SSE.
2. **Planner** returns a structured plan of at most 6 typed tasks: `data`, `literature` or `stats`.
3. **Workers** run tasks, up to 3 in parallel, each limited to its own tool subset. Every tool result is stored in the evidence ledger under an `evidence_id`.
4. **Drafter** writes findings as claims; each numeric claim must cite at least one `evidence_id`.
5. **Evidence checker** runs code checks first: every claim has evidence, and every number appears in its evidence within tolerance with matching units. Then one binary LLM check for non-numeric support. Failing claims go back to the drafter, at most twice; claims still failing are marked unsupported and excluded from the summary.
6. **Reporter** assembles the report JSON and Markdown and closes the run.

Budget guards stop any run at 20 tool calls, 150,000 input tokens or 180 seconds, saving a partial report with status `budget_exceeded`. **Single-agent mode** replaces steps 2–4 with one tool-calling loop over all tools, but keeps the same ledger, checker and report schema, so the two modes compare fairly.

**D. Eval run**

1. Load the golden set; compute or load cached truth values with DuckDB over the raw layer.
2. Call `agent-service` in eval mode: temperature 0, pinned model ID, prompt versions recorded.
3. Grade each case, store results in `eval_run` and `eval_case_result`, and compare with the stored baseline.
4. Fail the CI job if any gate threshold in the evaluation spec is breached.

## 5. Architecture decision records

All ADRs start as Proposed. Siddharth accepts or rejects each one before the work package that depends on it begins; agents copy accepted ADRs into `docs/adr/NNN-title.md` and never change them silently.

| ADR | Decision | Why | Rejected alternative |
| --- | --- | --- | --- |
| 001 | The model never writes SQL; it calls typed, parameterized, read-only tools | Removes injection and wrong-query classes; separates Cohortex from the Backblaze text-to-SQL demo | Text-to-SQL with a query checker |
| 002 | MCP data tools call `fleet-api`, never the database | One owner for data access, validation and limits; the Java API is reusable outside the agent | Tools with their own DB connections |
| 003 | Postgres + pgvector holds serving data and corpus vectors | One store to operate; hybrid search with full-text in the same query | Separate vector database |
| 004 | Parquet + DuckDB raw layer is the eval truth source | Independent path from serving tables, so grading is a real cross-check | Truth computed from Postgres |
| 005 | Kafka carries replay events and alerts only; backfill uses bulk `COPY` | Streaming where it adds realism, bulk where it is cheaper | All ingest through Kafka |
| 006 | LangGraph orchestrates both agent modes behind one interface | Explicit state graph, checkpoints, and easy A/B of modes | Custom loop or a multi-agent framework |
| 007 | AFR uses Backblaze's formula with exact Poisson 95% intervals | Matches published reports; intervals expose small-cohort noise | Plain AFR without uncertainty |
| 008 | Every claim carries `evidence_ids`; numbers are checked by code before any LLM check | Cheap, deterministic grounding; LLM judgment only where code cannot decide | LLM-only faithfulness check |
| 009 | Tracing follows OpenTelemetry GenAI semantic conventions | Vendor-neutral; the MCP Python SDK 2.x already emits these spans | Vendor-specific SDK only |
| 010 | Model access goes through one provider interface configured by environment | Swap Anthropic, OpenAI or a local model without code changes; pin models per run | Direct SDK calls in nodes |
| 011 | Java for ingest streaming and the fleet API; Python for analytics, tools, agent and evals | Plays to existing Java strength while building Python AI depth | Single language |

## 6. Deployment and environments

Three environments share one set of container images; only configuration and data size differ.

| Environment | Runs on | Data | LLM | Purpose |
| --- | --- | --- | --- | --- |
| `local` | Docker Compose on a laptop or WSL2 | Fixture subset: 3 models × 1 quarter, about 1% of rows | Real provider, or recorded responses | Development |
| `ci` | GitHub Actions, ephemeral Compose and Testcontainers | Same fixture, checked into Git LFS or built in CI | Recorded responses on every PR; small live subset nightly | Tests and eval gate |
| `demo` | Kubernetes on one managed cloud via Terraform and Helm | Six Backblaze quarters + Alibaba | Real provider with a spending cap | Public portfolio demo |

**Demo rules:** the public mode is read-only and rate-limited (5 investigations per IP per day); the owner mode sits behind a single admin token. A hard monthly LLM spend cap is enforced in `agent-service`. Raw Parquet lives in object storage, not on cluster disks. Choose one cloud only: Azure matches Micron's postings, AWS matches Amazon's.
