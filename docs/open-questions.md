# Open questions

Anything the specs do not settle goes here, never into invented behavior. Each entry names who
decides and which work package is blocked. Move resolved items to the bottom with the answer.

| # | Question | Raised in | Blocks | Decider | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Accept or reject ADRs 001–012 (all `Proposed`) | WP-00 | WP-01 onward | Siddharth | Open |
| 2 | Confirm the exact Backblaze non-SMART columns and Alibaba field names against the official schema files | WP-00 (spec marks them *verify*) | WP-01, WP-03 | WP-01 agent, reviewed by Siddharth | Open |
| 3 | Which LLM provider and pinned model ID for development and graded runs, and the monthly budget | WP-00 | WP-06 | Siddharth | Open |
| 4 | Embedding model and dimension (provisional: BAAI/bge-small-en-v1.5, 384) | WP-00 | WP-10 (and the `chunk.embedding` column in WP-02) | Siddharth | Open |
| 5 | Final project name: re-check "Cohortex" on GitHub, PyPI and npm before creating the public repo | Spec overview | Public repo creation | Siddharth | Open |
| 6 | Cloud for the demo: Azure (Micron alignment) or AWS (Amazon alignment) | Design §6 | WP-17 | Siddharth | Open |
| 7 | Code license: MIT chosen as a default in WP-00 | WP-00 | Public repo creation | Siddharth | Open |
| 8 | Fixture strategy for CI: commit a small attributed fixture or build it in CI from a downloaded quarter (Git LFS vs generation) | Design §6 | WP-01 | Siddharth | Open |
