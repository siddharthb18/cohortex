# C6 mcp-stats

Pure statistics MCP tools: `afr_ci`, `compare_rates`, `change_point`.

- **Built in:** WP-05 (see [build plan](/docs/specs/build-plan.md))
- **Contracts:** [contracts §5](/docs/specs/contracts.md), schemas and descriptions in
  [`contracts/tools/`](/contracts/tools/), methods in [implementation notes §4](/docs/implementation-notes.md)
- **Covers:** FR-TOOL-1, 2, 3, 4, 5, 6 (shared plumbing in [`mcp-common`](../mcp-common/README.md)), FR-ANA-1

## Run it

```bash
uv run python -m cohortex_mcp_stats            # streamable HTTP on 0.0.0.0:8102, MCP at /mcp, GET /healthz
uv run python -m cohortex_mcp_stats --stdio    # stdio, for MCP Inspector and local clients
uv run python -m cohortex_mcp_stats --host 127.0.0.1 --port 18102
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `COHORTEX_CONTRACTS_DIR` | the repo's `contracts/`, found by walking up from the installed package | Where `tools/manifest.json` and the schemas live (set it in containers) |

The server exits with status 2 and prints `refusing to start: ...` when a tool description or input
schema does not match its SHA-256 in `contracts/tools/manifest.json` (FR-TOOL-5).

## Try it in MCP Inspector

```bash
# stdio: Inspector launches the server itself
npx @modelcontextprotocol/inspector uv run python -m cohortex_mcp_stats --stdio

# or HTTP: start the server, then in Inspector pick "Streamable HTTP" and enter http://localhost:8102/mcp
uv run python -m cohortex_mcp_stats
npx @modelcontextprotocol/inspector
```

Call `afr_ci` with `{"failures": 3, "drive_days": 98189}`. Then try a bad input such as
`{"failures": "3; DROP TABLE drive"}`. You get `isError: true` and a short JSON error, not a stack trace.

## How it works

1. **Contracts first.** At startup the server reads the three tool descriptions from
   `contracts/tools/manifest.json` and checks each SHA-256, along with the hash of each input schema.
   Any difference stops startup. What the model sees is exactly what was reviewed.
2. **Validate, then compute.** Each `tools/call` is checked against the tool's JSON Schema
   (jsonschema 4.26, Draft 2020-12) before any code runs. Defaults are filled in, e.g. `confidence`
   0.95. Errors are built from the schema, never from the caller's text, so an injected string is
   never echoed back to the model.
3. **The statistics** (`stats.py`, scipy 1.18.1):
   - `afr_ci`: `afr_pct = failures × 365 × 100 / drive_days`. The exact Poisson interval uses the
     chi-square form: the lower count is `chi2.ppf(a, 2k)/2` (0 when k = 0), the upper count is
     `chi2.ppf(1−a, 2k+2)/2`, and `a = (1−confidence)/2`. Both are converted like the AFR. fleet-api
     (Java) uses the same formula. The test checks all 1,000 cases in
     `contracts/fixtures/afr_ci_cases.json` to 1e-9 relative.
   - `compare_rates`: condition on the total `k = ka + kb`. Under "same rate", `ka ~ Binomial(k, p0)`
     with `p0 = dda/(dda+ddb)`. The two-sided p-value is `scipy.stats.binomtest`. The ratio's 95%
     interval maps the Clopper-Pearson interval on `p` through `p/(1−p) · ddb/dda`. `null` means
     unbounded (no failures in B).
   - `change_point`: for every split of the series, compare "one rate" against "a rate before and a
     rate after". The statistic is the largest `2 × log-likelihood gain` (the terms that do not
     depend on the rates cancel). The p-value comes from simulating 999 constant-rate series
     (`numpy.random.default_rng(7)`): `(1 + #{simulated ≥ observed}) / 1000`. The fixed seed makes
     the same input give the same p-value, which the evidence checker relies on.
4. **Envelope.** Results are wrapped as `{evidence_id: "", tool: "stats.afr_ci", args, source,
   generated_at, data, truncated, next_page}`. The text content and `structuredContent` carry the
   same JSON. agent-service fills `evidence_id` when it records the call.

## Use it from Python (agent-service, tests)

```python
from mcp import Client
from cohortex_mcp_stats.server import build_server

async with Client(build_server()) as client:  # in-memory, protocol 2026-07-28
    result = await client.call_tool("afr_ci", {"failures": 3, "drive_days": 98189})
    envelope = result.structured_content  # result.is_error is False
```

## Tests

`uv run pytest mcp/mcp-stats -q`:
- `test_stats_functions.py`: the fixture at 1e-9, known `binomtest` values, a synthetic step change
  found at the right period, deterministic p-values, bad period orders.
- `test_stats_server.py`: an in-memory session that lists and calls every tool, fuzzed invalid inputs
  returning structured errors, the envelope schema, startup blocked by an edited description, and
  streamable HTTP with `/healthz` and a stdio subprocess.
