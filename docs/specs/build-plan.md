# Cohortex — Agent Build Plan

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes. The repo's live `CLAUDE.md` is at the root.

## 1. Operating rules and CLAUDE.md

One agent session builds one work package on one branch and ends with one pull request. Siddharth reviews, runs the explain-back check, and merges. The spec set is exported to Markdown in `docs/specs/`, so agents read it from the repo.

The repo root `CLAUDE.md` holds the agent instructions (derived from the template in the spec doc).

**Prompt to start any work package:** "Implement WP-NN from docs/specs/build-plan.md. Follow CLAUDE.md. Begin by listing the requirements and contracts you will satisfy and the tests you will write; then proceed."

## 2. Work packages

Nineteen work packages in four phases. Phase 1 (WP-00 to WP-08) is the Oct 31 MVP; each later phase starts only after the previous gate. Work packages with no dependency between them can run as parallel agent sessions on separate branches.

| WP | Title | Depends on | Delivers (requirement IDs) | Human checkpoint |
| --- | --- | --- | --- | --- |
| **Phase 1 · MVP (Oct 3 – Oct 31)** | | | | |
| WP-00 | Repo bootstrap and version pinning | — | Monorepo skeleton, Makefile, Compose (Postgres + pgvector, Kafka KRaft, OTel Collector, Jaeger), CI skeleton, `docs/versions.md`, MCP-adapter decision; FR-OPS-4, FR-OPS-5 (skeleton) | Accept ADRs 001–011 |
| WP-01 | Dataset verification and fixtures | WP-00 | Confirmed Backblaze and Alibaba field lists; fixture subset (3 models × 1 quarter) with attribution | Approve fixture choice |
| WP-02 | Serving schema | WP-00 | Flyway `V1__init.sql` from the contracts file; migration tests | — |
| WP-03 | Batch ingest (Backblaze) | WP-01, WP-02 | `ingest-batch`, raw layer, DuckDB views; FR-ING-1..5 | Read reconciliation output |
| WP-04 | Fleet API core | WP-02, WP-03 | FR-API-1, 2, 3, 7, 8; FR-ANA-1 (Java side) | Explain-back: AFR and CI math |
| WP-05 | MCP fleet and stats servers | WP-04 | FR-TOOL-1, 2, 3, 4, 6; stats tools; Java–Python CI agreement test | Try tools in MCP Inspector |
| WP-06 | Agent service, single mode | WP-05 | Provider interface, evidence ledger, checker, budgets, report; FR-AGT-1, 2, 5–9 | Explain-back: graph and checker |
| WP-07 | Eval harness MVP | WP-03, WP-06 | Loader, truth runner, code graders, recordings, CI gate; FR-EVAL-1, 2, 3, 6; 30 drafted cases | **Review all 30 cases** |
| WP-08 | Minimal investigation UI | WP-06 | FR-UI-5; demo video script | Record the 2-minute demo |
| **Phase 2 · Depth (Nov 1 – Nov 30)** | | | | |
| WP-09 | Alibaba ingest and SMART APIs | WP-03, WP-04 | FR-ING-6, FR-API-4, FR-API-5 | — |
| WP-10 | Corpus and docs server | WP-02, WP-05 | `corpus-indexer`, `mcp-docs`; FR-RAG-1..4, FR-EVAL-4 | **Approve corpus manifest; label retrieval pairs** |
| WP-11 | Orchestrated mode | WP-06, WP-10 | FR-AGT-3, 4, 10, 11 | Explain-back: planner and workers |
| WP-12 | Tracing, metrics, review tool | WP-06 | FR-OPS-1..3, FR-EVAL-8; Grafana dashboards | **Error analysis on ~100 traces** |
| **Phase 3 · Platform (Dec 11 – Jan 10)** | | | | |
| WP-13 | Streaming replay | WP-02 | `stream-ingest` producer and consumer; FR-ING-7, 8; NFR-PERF-4 | — |
| WP-14 | Alerts and risk model | WP-13 | `analytics-worker`; FR-ANA-2..4, FR-API-6 | Explain-back: change detection |
| WP-15 | Full UI | WP-08, WP-14 | FR-UI-1..4, 6, 7, 8 | — |
| WP-16 | Judge, adversarial suite, gate hardening | WP-07, WP-11 | FR-EVAL-5, 7; FR-TOOL-5; NFR-SEC-2 | **Label 60 claims; accept judge** |
| WP-17 | Cloud deployment | WP-15, WP-16 | Helm, Terraform, demo mode, rate limit, spend cap; NFR-SEC-4, NFR-COST-2, 3 | Approve cloud choice and budget alert |
| WP-18 | Experiment and launch | WP-11, WP-16, WP-17 | Single-vs-orchestrated study; README, blog post, eval dashboard | **Write the blog post** |
| **Phase 4 · Stretch (Jan 11 – Feb 28)** | | | | |
| WP-19 | LLM inference memory profiling | WP-17 | Open model on the local GPU or a free Kaggle T4 (no TAMU HPRC); KV-cache memory vs context length and batch size; write-up | Owns the analysis |

**Golden-case drafting rule (WP-07 onward).** Agents may draft candidate questions and `truth_sql`, but a case enters the gate only after Siddharth runs the SQL himself, checks the answer makes sense, and sets `reviewed_by`.

## 3. Human-owned tasks and explain-back checklist

These are the parts that make the project yours and keep every resume line truthful. Agents may build the tooling around them, never the judgments themselves.

- [ ] Accept or reject ADRs 001–011 before WP-00 merges
- [ ] Approve the fixture subset and the corpus manifest
- [ ] Review and sign off every golden case (`reviewed_by`)
- [ ] Label retrieval relevance pairs for M6
- [ ] Run error analysis on ~100 traces and write `docs/failure-taxonomy.md`
- [ ] Hand-label 60 atomic claims and accept or reject the judge
- [ ] Interpret the single-vs-orchestrated results and choose the default mode
- [ ] Write the README story, the blog post and the resume bullets from real numbers

**Explain-back check (after every work package, about 15 minutes, no AI help):**

1. Draw the component's data flow from memory.
2. Explain why each ADR it relies on was chosen and what the rejected alternative would have cost.
3. Make one small change yourself: a new parameter, a new test, or a new tool field.
4. Answer: what breaks first under 10× data, and how would you see it in the traces?
5. Note anything you could not explain in `docs/learning-log.md` and study it before the next work package.

Passing these checks is what turns "Claude built it" into "I designed, directed, evaluated and can defend it," which is the honest framing for interviews.
