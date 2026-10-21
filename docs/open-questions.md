# Open questions

Anything the specs do not settle goes here, never into invented behavior. Each entry names who
decides and which work package is blocked. Move resolved items to the bottom with the answer.

| # | Question | Raised in | Blocks | Decider | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Accept or reject ADRs 001–013 | WP-00 | WP-01 onward | Siddharth | Resolved 2026-10-02: all accepted; ADR-013 revised first to drop TAMU HPRC |
| 2 | Confirm the exact Backblaze non-SMART columns and Alibaba field names against the official schema files | WP-00 (spec marks them *verify*) | WP-01, WP-03 | WP-01 agent, reviewed by Siddharth | Open |
| 3 | Which LLM provider and pinned model ID for development and graded runs, and the monthly budget | WP-00 | WP-06 | Siddharth | Resolved by ADR-013 ($0: gpt-oss-20b via Groq free tier / local Ollama / Kaggle) |
| 4 | Embedding model and dimension | WP-00 | WP-10 (and the `chunk.embedding` column in WP-02) | Siddharth | Resolved by ADR-013 (BAAI/bge-small-en-v1.5, 384, local fastembed) |
| 5 | Final project name: re-check "Cohortex" on GitHub, PyPI and npm before creating the public repo | Spec overview | Public repo creation | Siddharth | Open |
| 6 | Cloud for the demo under a $0 budget: free tiers or student credits (Azure for Students, AWS Educate, GitHub Student Pack); Azure aligns with Micron | Design §6 | WP-17 | Siddharth | Open |
| 7 | Code license: MIT chosen as a default in WP-00 | WP-00 | Public repo creation | Siddharth | Open |
| 8 | Fixture strategy for CI: commit a small attributed fixture or build it in CI from a downloaded quarter (Git LFS vs generation) | Design §6 | WP-01 | Siddharth | Open |
| 9 | Dev PC RAM/GPU: can it run `gpt-oss-20b` locally (about 16 GB RAM or VRAM)? If not, Groq free tier only for development | ADR-013 | WP-06 (offline dev only) | Siddharth | Open |
| 10 | Where graded eval runs happen: local Ollama if the dev PC can hold gpt-oss-20b, else a Kaggle GPU notebook (needs a phone-verified Kaggle account). TAMU HPRC is not used | ADR-013 | WP-07 live runs, WP-18, WP-19 | Siddharth | Open |
| 11 | Tianchi account to download the Alibaba SSD logs (dataset 95044 needs a login) | WP-00 dataset check | WP-09 | Siddharth | Open |
| 12 | Backblaze schema files and quarter ZIPs could not be fetched from the build sandbox; verify on the dev PC or in a GitHub Actions job | WP-00 dataset check | WP-01 | WP-01 agent | Open |
| 13 | Per-investigation input-token budget on the Groq free tier (proposed 40,000 on Groq vs 150,000 on local or Kaggle runs) | ADR-013 | WP-06 | Siddharth | Open |
| 14 | Backblaze data includes some boot SSDs; Phase 1 labels every Backblaze row `hdd` (implementation-notes §3) | WP-03 | — | Siddharth | Default applied |
| 15 | Definitions the specs left open (drive_count, min_drives, window rule, 1% sample hash, Alibaba failed_on): see docs/implementation-notes.md §3–5 | WP-03/04 | — | Siddharth | Default applied |
| 16 | Statistics methods for compare_rates and change_point (implementation-notes §4) | WP-05 | — | Siddharth | Default applied |
| 17 | Paged response shape `{items, page, size, total}` for fleet-api lists | WP-04 | — | Siddharth | Default applied |
| 18 | Extra endpoint `GET /v1/investigations` (recent list) for the UI | WP-06/08 | — | Siddharth | Default applied |
| 19 | MCP list tools take an optional `page` (0–999) and split results into ≤ 4 KB pages so no rows are lost; `failed_drives` pages over the first 500 failures, ≤ 25 rows per page | WP-05 | — | Siddharth | Default applied |
| 20 | `smart_trend` takes optional `granularity`; `list_models` sorted by drive_count descending; model-name pattern requires a leading alphanumeric and rejects `--` | WP-05 | — | Siddharth | Default applied |
| 21 | Investigation `scope` accepts both `from`/`to` (contracts §4) and `date_from`/`date_to` (contracts §6); stored in the §6 shape | WP-06/07 | — | Siddharth | Default applied |
| 22 | Numeric tolerance (0.5% relative or 0.01 absolute) also applies to `ratio`, `p_value` and `raw` units; counts, drive-days and days must match exactly | WP-06/07 | — | Siddharth | Default applied |
| 23 | M7 (refusal) and M8 (injection) enforced in the PR gate already, ahead of Phase 2 | WP-07 | — | Siddharth | Default applied |
| 24 | Diagnostic truth = smallest set of models, ranked by excess failures, explaining ≥ 50% of the fleet change; grader counts models named in summary and hypotheses | WP-07 | — | Siddharth | Default applied |
| 25 | Retrieval recall uses the order passages are cited until WP-10 records search results; optional case fields `canary`, `accept_statuses`, `fixture`, `relevant_passages`; if both `abs_tol` and `rel_tol` are set, either suffices | WP-07 | — | Siddharth | Default applied |
