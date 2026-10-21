# C5 mcp-fleet

Typed, read-only MCP tools over fleet-api: `list_models`, `cohort_afr`, `compare_cohorts`,
`fleet_summary`, `smart_trend`, `failed_drives`.

- **Built in:** WP-05 (see [build plan](/docs/specs/build-plan.md))
- **Contracts:** [contracts §4–5](/docs/specs/contracts.md), [`contracts/tools/`](/contracts/tools/),
  [implementation notes §5–6](/docs/implementation-notes.md)
- **Decisions:** ADR-001 (no SQL, URLs or paths in tools), ADR-002 (tools call fleet-api, never the database)
- **Covers:** FR-TOOL-1, 2, 3, 4, 5, 6

## Run it

```bash
FLEET_API_URL=http://localhost:8080 uv run python -m cohortex_mcp_fleet          # HTTP 0.0.0.0:8101 /mcp, GET /healthz
FLEET_API_URL=http://localhost:8080 uv run python -m cohortex_mcp_fleet --stdio  # stdio
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `FLEET_API_URL` | `http://localhost:8080` | fleet-api base URL |
| `COHORTEX_CONTRACTS_DIR` | the repo's `contracts/` | Where the pinned tool contracts live |

`/healthz` is liveness only. It does not call fleet-api.

## Try it in MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run python -m cohortex_mcp_fleet --stdio
# or: start the HTTP server and connect Inspector ("Streamable HTTP") to http://localhost:8101/mcp
```

Every call needs fleet-api running. Without it, calls return
`{"error": {"code": "upstream_error", "message": "fleet-api is unreachable"}}`, which is itself a
useful thing to see in Inspector.

## Tools and limits

| Tool | fleet-api call | `data` | Limits enforced here |
| --- | --- | --- | --- |
| `list_models` | `GET /v1/models` (walks 500-row pages) | `[{model, media, capacity_bytes, drive_count}]`, largest `drive_count` first | `media` / `min_drives` filters; ≤ 100 rows |
| `cohort_afr` | `GET /v1/cohorts/{source}/{model}/afr` | fleet-api body (`series`, `method`, …) | window ≤ 8 quarters, `to ≥ from` |
| `compare_cohorts` | `GET /v1/cohorts/compare` | `{items: [...], ...}` | `limit` ≤ 20 (default 20), `min_drives` default 60 |
| `fleet_summary` | `GET /v1/fleet/summary` | fleet-api body | window ≤ 8 quarters |
| `smart_trend` | `GET /v1/cohorts/{source}/{model}/smart-trend` | fleet-api body (`series` with `n_drives` = sample size) | `attr` must be kept for that source |
| `failed_drives` | `GET /v1/cohorts/{source}/{model}/failed-drives?page=0&size=500` | `{total, items}` | ≤ 25 drives per page; the first 500 failures can be paged |

Every result is at most 4 KB of compact JSON. Longer results are split into pages (`page`,
`truncated`, `next_page`); see [`mcp-common`](../mcp-common/README.md) for the paging rule.

## How it works

1. **Startup** checks descriptions and schemas against `contracts/tools/manifest.json` and refuses to
   start on a mismatch (FR-TOOL-5).
2. **Each call** is validated against its JSON Schema first. `source` and `granularity` are enums,
   `model` is `^(?!.*--)[A-Za-z0-9][A-Za-z0-9_.\- ]{0,63}$` (no quotes, `;`, `/`, `:`, `=`), dates
   are `YYYY-MM-DD` and real dates, and every number has bounds. SQL, URLs and paths cannot get
   through (FR-TOOL-4). Bad input never reaches fleet-api; a test asserts zero HTTP requests.
3. **Tool rules** run next: the window must be 1–8 calendar quarters, and `attr` must be one of the
   source's kept SMART attributes. Then `FleetApiClient` (httpx) makes the GET. The model name is
   percent-encoded into the path, so `HGST HUH721212ALE604` becomes `HGST%20HUH721212ALE604`.
4. **Responses** are parsed with Pydantic models. Unknown extra fields are kept, but a missing
   documented field becomes `upstream_error`, so a contract drift in fleet-api shows up as a clear
   error. Problem details map to error codes: 400/422 → `invalid_argument` (the `detail` text is
   included, cleaned and capped), 404 → `not_found`, 413 → `too_large`, anything else, including
   timeouts and refused connections → `upstream_error` with a generic message. No upstream stack
   trace is ever forwarded.
5. **Envelope and 4 KB cap**: the shared `finalize` wraps the data and pages lists.

## Use it from Python (agent-service, tests)

```python
import httpx
from mcp import Client
from cohortex_mcp_fleet.client import FleetApiClient
from cohortex_mcp_fleet.server import build_server
from cohortex_mcp_fleet.testing import FakeFleetApi

fake = FakeFleetApi()                                   # contract-shaped fake fleet-api
async with Client(build_server(fleet=fake.client())) as client:
    result = await client.call_tool("fleet_summary",
        {"source": "backblaze", "from": "2026-04-01", "to": "2026-06-30"})

# against a real fleet-api, or your own httpx.MockTransport:
fleet = FleetApiClient(http_client=httpx.AsyncClient(base_url="http://fleet-api:8080"))
server = build_server(fleet=fleet)
```

## Tests

`uv run pytest mcp/mcp-fleet -q`:
- `test_fleet_client.py`: query parameters, path encoding, problem-detail and network-error mapping,
  unexpected response shapes.
- `test_fleet_server.py`: an in-memory session over all six tools, window and attr rules, a
  1,200-model list capped at 100 and paged losslessly within 4 KB (FR-TOOL-6), failed-drive pages
  (≤ 25 rows, ≤ 4 KB, `total`), structured errors for every fleet-api failure, fuzzed and injected
  inputs that never reach fleet-api, startup blocked by an edited description, streamable HTTP with
  `/healthz`, and a static check that the package has no database client (ADR-002).
