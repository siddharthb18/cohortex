# Checkpoint — 2026-10-22 (resume here)

**Start a new session with:** "Resume Cohortex from docs/CHECKPOINT.md in C:\Users\aftri\Documents\finalProject."

## Done (all on `main`, synced to the PC)
- All ADRs 001–013 Accepted ($0 stack: gpt-oss-20b via Groq free tier / local Ollama / Kaggle; no TAMU HPRC).
- Every Phase 1 component is built, merged and tested:
  - WP-01/02/03 data: `db/migrations/V1__init.sql`, `pipelines/ingest-batch` (Backblaze + Alibaba, synthetic
    fixture in `data/fixtures/`, `cohortex-ingest seed|backfill|build-fixture`).
  - WP-04 `services/fleet-api` (Java 25 / Spring Boot 4.1.1): compiles; 39 JUnit tests pass incl. integration
    tests against real Postgres (run here with JDK 21 and a local DB).
  - WP-05 `mcp/mcp-common|mcp-stats|mcp-fleet`; WP-06/11 `services/agent-service` (single + orchestrated);
    WP-07 `evals/harness` + 30 draft golden cases; WP-08 `services/web-ui` (+ static demo mode, screenshots in
    `services/web-ui/docs/screenshots/`).
- Python: 368 tests pass. Web UI: 49 unit + 5 Playwright e2e pass.
- Verified end to end on seeded data: fleet-api (Java) → mcp-fleet/mcp-stats over HTTP → all 8 tool calls OK;
  agent run against the real MCP servers passes (`services/agent-service/tests/test_integration_mcp.py`).
- Compose runs the whole stack (`make up && make seed`, UI on :5173); CI has Postgres, web-ui, manifest jobs.

## Not yet done (next steps for Claude)
1. **Live LLM run** — blocked on a Groq API key (Siddharth must sign in at console.groq.com in the browser
   pane; Claude then creates the key and writes `.env`). Then: run 2–3 real investigations, record them
   (`COHORTEX_LLM_MODE=record`), add the recorded-response eval gate to CI, export one run as the web-ui
   demo JSON.
2. **Real data**: `make backfill QUARTER=2026Q2` (Backblaze is reachable now), then `build-fixture` to replace
   the synthetic fixture, then `make truth` for the golden set.
3. **Not run yet**: `make up` with Docker (no Docker daemon in the cloud workspace) — first run on the PC.
   Spotless check could not run here (google-java-format on JDK 21); CI runs it on JDK 25.
4. Publish: GitHub repo + GitHub Pages demo (`npm run build:demo`), README rewrite with screenshots,
   metrics and resume bullets.
5. Phase 2 extras if time: mcp-docs + corpus-indexer (RAG), tracing, streaming replay.

## Environment notes
- Cloud workspace now reaches Maven Central and the Gradle plugin portal index, but **plugins-artifacts.gradle.org
  is blocked** (needed for foojay and Error Prone plugins). Local build workaround (do not commit): delete the
  foojay line in settings.gradle.kts and the errorprone lines in build.gradle.kts + services/fleet-api/build.gradle.kts,
  then `./gradlew --max-workers=1 :services:fleet-api:test -PjavaToolchain=21` with
  `COHORTEX_FLEET_TEST_JDBC_URL=jdbc:postgresql://localhost:5432/fleet_test?user=cohortex`. Retry on HTTP 429.
- Local Postgres 16 + pgvector (built from source) in the cloud workspace; restart with
  `su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/pgtest/data -o '-p 5432 -k /tmp' start"`.
- Sync to the PC with a git bundle; use a NEW bundle filename each time (the bridge reuses old content for the
  same name). Git in the PC folder needs delete permission (request once per session).
- Commits: author Claude <noreply@anthropic.com> with Co-Authored-By/Claude-Session trailers.

## Siddharth's actions (outstanding)
1. Sign in at console.groq.com in the browser pane (Claude desktop app, Ctrl+Shift+B) so Claude can create keys.
2. Add `plugins-artifacts.gradle.org` to allowed domains (Settings → Capabilities) so the full Java build runs here.
3. Tell Claude the PC's RAM and GPU (local Ollama vs Kaggle for graded runs).
4. On the PC: `make up && make seed`, open http://localhost:5173 (first Docker run).
5. Review the 30 golden cases (`evals/golden/v1/README.md`) and confirm open questions 14–25.
6. Create a GitHub repo to publish; Tianchi login for the real Alibaba data.
