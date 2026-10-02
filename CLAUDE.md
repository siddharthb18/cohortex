# Cohortex — agent instructions

## What this is
Agentic reliability investigations over public HDD/SSD fleet telemetry.
Specs: docs/specs/ (overview, design, SRS, ERS, contracts, evaluation, build plan).
Decisions: docs/adr/ (only `Accepted` ADRs are binding; `Proposed` ones need Siddharth first).
Pinned versions: docs/versions.md.

## Before writing code
1. Read docs/specs/ERS.md and the work package you were given in docs/specs/build-plan.md.
2. Read every SRS requirement and contract section the work package cites.
3. Check that every ADR the work package relies on is `Accepted`. If one is still `Proposed`,
   stop and say so.
4. If anything needed is unspecified or contradictory, add it to docs/open-questions.md
   and stop that part. Never invent behavior, endpoints, fields or thresholds.

## How to work
- Tests first: write the acceptance test named in the SRS, see it fail, then implement.
- Stay inside the work package's directories. Touch contracts/ only if the WP says so.
- No new dependency without adding it to docs/versions.md with a one-line reason.
- Never call a live LLM in tests; use evals/recordings/.
- Never commit secrets, raw datasets, or files over 5 MB.
- The model never writes SQL and tools never accept SQL, URLs or paths (ADR-001).
- One branch and one pull request per work package, named `wp-NN-short-title`.
- Conventional Commits (`feat(fleet-api): ...`, `test(evals): ...`, `chore: ...`).

## Commands
- `make help` lists everything.
- `make up` / `make down` start and stop local infrastructure (Docker Compose).
- `make lint`, `make typecheck`, `make test` run the checks CI runs.
- Python: `uv sync --all-packages` installs the workspace; run tools with `uv run`.
- Java: `./gradlew build` from the repo root (JDK 25 is provisioned by Gradle toolchains).

## Done means
- `make lint typecheck test` passes locally; CI green.
- PR description lists the FR/NFR IDs covered, the tests that prove them,
  and anything deferred to docs/open-questions.md.
- A short "How it works" note in the component README that Siddharth can study.

## Never
- Write human-owned artifacts: error-analysis labels, judge validation labels,
  golden-set reviews (`reviewed_by`), ADR status changes, docs/failure-taxonomy.md.
- Change a gate threshold or golden-set truth to make CI pass.
- Weaken a test to make it pass.
