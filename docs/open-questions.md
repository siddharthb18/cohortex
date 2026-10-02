# Open questions

Anything the specs do not settle goes here, never into invented behavior. Each entry names who
decides and which work package is blocked. Move resolved items to the bottom with the answer.

| # | Question | Raised in | Blocks | Decider | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Accept or reject ADRs 003–013 (001 and 002 accepted 2026-10-02) | WP-00 | WP-02 onward | Siddharth | Open |
| 2 | Confirm the exact Backblaze non-SMART columns and Alibaba field names against the official schema files | WP-00 (spec marks them *verify*) | WP-01, WP-03 | WP-01 agent, reviewed by Siddharth | Open |
| 3 | Which LLM provider and pinned model ID for development and graded runs, and the monthly budget | WP-00 | WP-06 | Siddharth | Proposed in ADR-013 ($0: gpt-oss-20b via Groq free tier / Ollama / vLLM on HPRC) |
| 4 | Embedding model and dimension | WP-00 | WP-10 (and the `chunk.embedding` column in WP-02) | Siddharth | Proposed in ADR-013 (BAAI/bge-small-en-v1.5, 384, local fastembed) |
| 5 | Final project name: re-check "Cohortex" on GitHub, PyPI and npm before creating the public repo | Spec overview | Public repo creation | Siddharth | Open |
| 6 | Cloud for the demo under a $0 budget: free tiers or student credits (Azure for Students, AWS Educate, GitHub Student Pack); Azure aligns with Micron | Design §6 | WP-17 | Siddharth | Open |
| 7 | Code license: MIT chosen as a default in WP-00 | WP-00 | Public repo creation | Siddharth | Open |
| 8 | Fixture strategy for CI: commit a small attributed fixture or build it in CI from a downloaded quarter (Git LFS vs generation) | Design §6 | WP-01 | Siddharth | Open |
| 9 | Dev PC RAM/GPU: can it run `gpt-oss-20b` locally (about 16 GB RAM or VRAM)? If not, Groq free tier only for development | ADR-013 | WP-06 (offline dev only) | Siddharth | Open |
| 10 | HPRC (Grace) GPU allocation for graded eval runs and WP-19; who sponsors the account | ADR-013 | WP-07 live runs, WP-18, WP-19 | Siddharth | Open |
| 11 | Tianchi account to download the Alibaba SSD logs (dataset 95044 needs a login) | WP-00 dataset check | WP-09 | Siddharth | Open |
| 12 | Backblaze schema files and quarter ZIPs could not be fetched from the build sandbox; verify on the dev PC or in a GitHub Actions job | WP-00 dataset check | WP-01 | WP-01 agent | Open |
| 13 | Per-investigation input-token budget on the Groq free tier (proposed 40,000 in `local` mode vs 150,000 on HPRC) | ADR-013 | WP-06 | Siddharth | Open |
