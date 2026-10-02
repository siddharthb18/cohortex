# Cohortex — Software Requirements Specification (SRS)

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes.

## 1. Introduction

**Purpose.** This SRS states what Cohortex must do and how well, in numbered requirements that each carry a priority and an acceptance test. Agents implement against these IDs, and every pull request names the IDs it satisfies.

**Scope.** Cohortex ingests public HDD and SSD fleet telemetry, detects cohort reliability shifts, and runs evidence-checked investigations that produce cited reports. It includes the evaluation harness that measures those reports. It excludes everything listed under non-goals in the design document.

**Priorities.** `MVP` = needed by the Phase 1 gate (Oct 31, 2026). `P2` = Phase 2 (November). `P3` = Phase 3 (Dec 11 – Jan 10). `P4` = stretch.

**Definitions**

| Term | Meaning |
| --- | --- |
| Drive-day | One drive observed on one day |
| Cohort | Drives sharing source and model, optionally narrowed by capacity or data center |
| AFR | Annualized failure rate: failures ÷ (drive-days ÷ 365) × 100% |
| Investigation | One run of the agent on one question, producing one report |
| Claim | One sentence in a report that asserts a fact, with zero or more numbers |
| Evidence | A stored tool call and result, referenced by `evidence_id` |
| Golden set | Versioned questions with truth computed independently from the raw layer |

**Personas**

- **Riya, reliability engineer.** Wants to know whether a cohort's rising failure rate is real, what drives it, and what to do. Trusts numbers only when she can trace them.
- **Reviewer.** A recruiter or hiring manager with five minutes. Wants a live demo, a clear README and visible quality metrics.
- **Maintainer (Siddharth).** Runs evals, reads traces, labels failures, and changes prompts and tools safely.

**References.** Design document, ERS, contracts file, evaluation spec; Backblaze Drive Stats; Alibaba SSD SMART logs; MCP specification 2026-07-28; OpenTelemetry GenAI semantic conventions.

## 2. Use cases

| ID | Actor | Goal | Main success path | Requirements |
| --- | --- | --- | --- | --- |
| UC-1 | Riya | Explore fleet reliability | Opens dashboard → sorts cohorts by 90-day AFR → opens a cohort → sees AFR trend with 95% intervals and SMART trends | FR-API-1..5, FR-UI-1..3 |
| UC-2 | Riya | React to a shift | Sees an alert in the inbox → reads ratio, p-value, window → clicks Investigate with the alert pre-filled | FR-ANA-2..4, FR-UI-4 |
| UC-3 | Riya | Investigate a question | Types or accepts a question → watches plan and tool steps stream → receives a cited report | FR-AGT-1..9 |
| UC-4 | Riya or Reviewer | Verify a claim | Clicks a number in the report → evidence drawer shows the tool call, arguments and returned value | FR-AGT-6, FR-UI-6 |
| UC-5 | Reviewer | Judge the project quickly | Opens the demo → runs a sample investigation → opens the public eval dashboard | FR-UI-7, FR-EVAL-7, NFR-SEC-4 |
| UC-6 | Maintainer | Change a prompt safely | Opens a PR → CI runs tests and the eval gate → sees per-metric deltas against baseline | FR-EVAL-1..6 |
| UC-7 | Maintainer | Find failure modes | Samples traces → labels failures in the review UI → exports a failure taxonomy | FR-EVAL-8, FR-OPS-3 |
| UC-8 | Maintainer | Add a new quarter | Runs backfill for the quarter → reconciliation passes → golden-set truth refreshes | FR-ING-1..6 |

## 3. Functional requirements

Each requirement is testable as written; the acceptance column is the test an agent must write first. "Truth" always means a value computed with DuckDB over the raw layer.

| ID | Requirement | Priority | Acceptance test |
| --- | --- | --- | --- |
| FR-ING-1 | Download a named Backblaze quarter, verify it, and record source URL, bytes and SHA-256 in `ingest_run` | MVP | Fixture quarter run creates one complete `ingest_run` row |
| FR-ING-2 | Convert each daily CSV to Parquet with lower-cased columns and a recorded schema version | MVP | Parquet row count equals CSV row count for every day |
| FR-ING-3 | Fail on any unknown non-SMART column, naming it | MVP | Fixture with an extra column fails with that column name |
| FR-ING-4 | Derive and load `drive`, `cohort_daily` and sampled `smart_daily`, one transaction per quarter, idempotently | MVP | Second run leaves all row counts unchanged |
| FR-ING-5 | Reconcile drive-days and failures per model between raw and serving layers; fail on mismatch | MVP | Corrupting one serving row makes reconciliation fail |
| FR-ING-6 | Ingest Alibaba SSD SMART logs and failure labels into the same schemas with `source = 'alibaba'` | P2 | All six Alibaba models present; failures match the label file |
| FR-ING-7 | Replay producer emits events for a date range at a configurable speed | P3 | 7 replayed days produce exactly the expected event counts |
| FR-ING-8 | Stream consumer updates are idempotent by event ID | P3 | Replaying a day twice leaves counts unchanged |
| FR-API-1 | `GET /v1/models` lists models with source, capacity and drive count | MVP | Matches truth for the fixture |
| FR-API-2 | `GET /v1/cohorts/{source}/{model}/afr` returns AFR, 95% CI, drive-days and failures by quarter or month | MVP | Counts equal truth; AFR within 1e-9 |
| FR-API-3 | `GET /v1/cohorts/compare` ranks cohorts in a window with rate ratios against the fleet | MVP | Ranking equals truth ranking |
| FR-API-4 | `GET /v1/cohorts/{source}/{model}/smart-trend` returns p50, p95 and non-zero share for one attribute over time | P2 | Values equal truth on the sampled set |
| FR-API-5 | `GET /v1/cohorts/{source}/{model}/failed-drives` lists failures with age at failure and last SMART values | P2 | Count equals truth |
| FR-API-6 | `GET /v1/alerts` lists open and resolved alerts | P3 | Created alert appears with all fields |
| FR-API-7 | All endpoints documented in OpenAPI 3.1; errors use RFC 9457 problem details | MVP | Contract tests pass against the generated spec |
| FR-API-8 | Pages hold at most 500 rows; windows longer than 8 quarters are rejected with 400 | MVP | Boundary tests pass |
| FR-ANA-1 | AFR 95% intervals use the exact Poisson method, identical in Java and Python | MVP | Cross-language test agrees to 1e-9 on 1,000 random cases |
| FR-ANA-2 | On day-closed, run change detection: rate ratio vs prior 90 days, minimum 60 drives and 3 failures | P3 | Synthetic step change raises an alert; flat data does not |
| FR-ANA-3 | Keep one open alert per cohort; auto-resolve after 14 clear days | P3 | Duplicate trigger updates, not inserts |
| FR-ANA-4 | Train a 30-day failure-risk model on sampled SMART data with a time-based holdout; expose elevated-risk counts per cohort | P3 | PR-AUC reported; no future data in training features |
| FR-TOOL-1 | MCP servers implement spec 2026-07-28 over stateless HTTP, plus stdio for local use | MVP | MCP Inspector lists and calls every tool |
| FR-TOOL-2 | Every tool has bounded JSON Schemas; bad input returns a structured error without stack traces | MVP | Fuzz test with invalid inputs |
| FR-TOOL-3 | Every result carries `evidence_id`, source, arguments and `generated_at` | MVP | Schema test on all tools |
| FR-TOOL-4 | Tools are read-only and accept no SQL, URLs or file paths | MVP | Static check of schemas; injection strings rejected |
| FR-TOOL-5 | Tool descriptions are pinned by hash; a server refuses to start on mismatch | P3 | Edited description blocks startup |
| FR-TOOL-6 | Serialized results are capped at 4 KB; larger results paginate | MVP | Large cohort list paginates |
| FR-AGT-1 | `POST /v1/investigations`, `GET /v1/investigations/{id}`, SSE stream of steps | MVP | End-to-end test receives steps then a report |
| FR-AGT-2 | Single-agent mode | MVP | Golden-set run completes |
| FR-AGT-3 | Orchestrated mode: planner, workers, drafter, evidence checker, reporter | P2 | Golden-set run completes |
| FR-AGT-4 | Plans validate against the plan schema; one repair attempt, then fail cleanly | P2 | Malformed plan fixture triggers repair |
| FR-AGT-5 | Every tool call and result is written to the evidence ledger | MVP | Ledger count equals tool-call count |
| FR-AGT-6 | Every numeric claim cites evidence; numbers are verified in code within tolerance | MVP | Fabricated number fixture is caught |
| FR-AGT-7 | Unsupported claims are excluded from the summary and listed as unverified | MVP | Fixture claim appears only under unverified |
| FR-AGT-8 | Budget guards: 20 tool calls, 150,000 input tokens, 180 s | MVP | Each guard fires in a test |
| FR-AGT-9 | Reports render as JSON and Markdown, with a limitations section naming triggered dataset caveats | MVP | Schema validation passes |
| FR-AGT-10 | Out-of-scope questions get a short refusal | P2 | Adversarial cases pass |
| FR-AGT-11 | Literature claims cite passage IDs and document URLs | P2 | Citation present on every literature claim |
| FR-RAG-1 | A corpus manifest records each document's URL and access basis; only openly published documents are indexed | P2 | Manifest check in CI |
| FR-RAG-2 | Chunks of 400–800 tokens with section anchors, stored with embeddings and a full-text index | P2 | Index build test |
| FR-RAG-3 | Hybrid search fuses full-text and vector results with reciprocal rank fusion | P2 | Recall@5 meets the eval threshold |
| FR-RAG-4 | `docs.get_passage` returns at most 1,200 characters plus citation | P2 | Length test |
| FR-UI-1 | Fleet dashboard: sortable cohort table | P3 | Playwright test sorts by AFR |
| FR-UI-2 | Cohort page: AFR over time with 95% interval whiskers | P3 | Visual snapshot test |
| FR-UI-3 | SMART trend chart per attribute | P3 | Visual snapshot test |
| FR-UI-4 | Alert inbox with Investigate action | P3 | Click pre-fills the question |
| FR-UI-5 | Investigation page: question box, live step list, report view | MVP | Playwright end-to-end test |
| FR-UI-6 | Clicking a number opens its evidence | P2 | Drawer shows tool, arguments, value |
| FR-UI-7 | Public eval dashboard with latest metrics and trend | P3 | Renders from stored eval runs |
| FR-UI-8 | Keyboard navigation and contrast meet WCAG 2.2 AA basics | P3 | axe-core reports no serious issues |
| FR-EVAL-1 | Golden set is versioned JSONL; each case stores truth SQL and truth value | MVP | Loader validates the schema |
| FR-EVAL-2 | Runner calls `agent-service` in eval mode with bounded concurrency | MVP | 30-case run completes |
| FR-EVAL-3 | Code graders: numeric tolerance, required entities, citation presence | MVP | Grader unit tests |
| FR-EVAL-4 | Retrieval eval reports recall@k on labeled pairs | P2 | Report produced |
| FR-EVAL-5 | Binary faithfulness judge, used in the gate only after validation | P3 | Validation report meets thresholds |
| FR-EVAL-6 | CI gate fails a PR that breaches any threshold | MVP | Deliberately broken prompt fails CI |
| FR-EVAL-7 | Results stored and published as JSON and Markdown | P3 | Dashboard reads them |
| FR-EVAL-8 | Trace review tool for open coding and labeling | P2 | Labels export to CSV |
| FR-OPS-1 | OpenTelemetry traces across all services; trace ID in every log line | P2 | One investigation shows one connected trace |
| FR-OPS-2 | Metrics per investigation: tokens, cost, latency, tool errors | P2 | Prometheus scrape shows them |
| FR-OPS-3 | Export traces for labeling | P2 | Export command works |
| FR-OPS-4 | Health and readiness endpoints on every service | MVP | Compose health checks pass |
| FR-OPS-5 | One command starts the local stack with fixture data | MVP | `make up && make seed` works on a clean machine |

## 4. Non-functional requirements

| ID | Requirement | Target | How verified |
| --- | --- | --- | --- |
| NFR-PERF-1 | Investigation latency | p50 ≤ 60 s, p95 ≤ 150 s on the golden set | Eval run timing |
| NFR-PERF-2 | Fleet API latency for cohort queries | p95 ≤ 300 ms at 20 requests/s | k6 load test in CI nightly |
| NFR-PERF-3 | Backfill of one Backblaze quarter | ≤ 30 min on an 8-core laptop with 16 GB RAM | Timed run, logged |
| NFR-PERF-4 | Replay throughput | ≥ 1 simulated day per 30 s without consumer lag growth | Lag metric stays flat for 20 days |
| NFR-REL-1 | Investigation success (report produced, not budget-killed) | ≥ 95% of golden-set cases | Eval run |
| NFR-REL-2 | Service restarts lose no completed investigations | 0 lost | Kill-pod test during a run |
| NFR-REL-3 | LLM provider errors are retried with backoff, max 3 attempts | Implemented | Fault-injection test |
| NFR-SEC-1 | No secrets in Git; all secrets via environment or a secret store | 0 findings | gitleaks in CI |
| NFR-SEC-2 | Prompt-injection resistance: planted instructions in documents or tool output are not followed | 100% of adversarial cases | Adversarial suite |
| NFR-SEC-3 | Dependencies scanned; no critical vulnerabilities at release | 0 critical | Dependabot plus Trivy on images |
| NFR-SEC-4 | Public demo is read-only and rate-limited; owner mode behind an admin token | Enforced | API tests |
| NFR-COST-1 | Mean LLM cost per investigation | ≤ $0.25 | Cost metric in eval report |
| NFR-COST-2 | Monthly demo LLM spend | Hard cap, default $25, enforced in code | Unit test of the cap |
| NFR-COST-3 | Monthly cloud spend for the demo | ≤ $40 target | Cloud budget alert |
| NFR-MAINT-1 | Test coverage of analytics, tools and graders | ≥ 85% lines | CI coverage report |
| NFR-MAINT-2 | Every prompt is a versioned file; every run records prompt hashes and model ID | 100% of runs | Schema check on `investigation` rows |
| NFR-OBS-1 | Each investigation forms one connected trace across agent, MCP servers and fleet API | 100% | Trace check in end-to-end test |
| NFR-UX-1 | First step of an investigation appears in the UI | ≤ 3 s after submit | Playwright timing |
| NFR-PORT-1 | Local stack runs on Linux, macOS, and Windows via WSL2 | Works | CI matrix for build; manual WSL2 check |
| NFR-LEGAL-1 | Dataset attribution as required by Backblaze and Alibaba; no raw data redistributed in the repo beyond small fixtures | Present in README and UI footer | Review checklist |
