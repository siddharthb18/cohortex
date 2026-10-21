# mcp-common

Shared plumbing for the Cohortex MCP servers (`mcp-fleet`, `mcp-stats`, and later `mcp-docs`), so all
of them validate, wrap, cap and pin their tools the same way.

- **Built in:** WP-05
- **Covers:** FR-TOOL-1 (runners), FR-TOOL-2, FR-TOOL-3, FR-TOOL-5, FR-TOOL-6

| Module | What it does |
| --- | --- |
| `contracts` | Finds `contracts/` (`$COHORTEX_CONTRACTS_DIR`, else by walking up from the package) and loads schemas |
| `manifest` | Pins descriptions and input schemas by SHA-256; `ManifestMismatchError` blocks startup |
| `validation` | jsonschema Draft 2020-12 with the date format checker; fills defaults; errors never echo input |
| `errors` | `ToolError(code, message)` → `{"error": {"code", "message"}}` (codes from implementation notes §6) |
| `envelope` | The evidence envelope, the 4 KB cap and lossless paging |
| `server` | `ToolRunner` (transport-free), `build_mcp_server` (MCP SDK 2.2 low-level `Server`), `build_http_app` (`/mcp` + `/healthz`), `run_cli` |
| `testing` | Test helpers: copy or edit contracts, fuzz cases, envelope and error assertions |
| `pytest_plugin` | Imports the MCP SDK before collection (see below) |

## How it works

**One call, start to finish.** `ToolRunner.call(name, arguments)`:
1. Validates the arguments against the pinned schema (`invalid_argument` on failure).
2. Runs the tool's handler, which returns `ToolOutput(source, data, paging)`.
3. Wraps the result in the envelope and enforces 4 KB with `finalize`.

Any `ToolError` becomes an `isError: true` result. Any other exception is logged on the server and
becomes `upstream_error: "internal tool error"`, so no stack trace reaches the client.

**Pinned descriptions (FR-TOOL-5).** `contracts/tools/manifest.json` stores each description, its
SHA-256 and the SHA-256 of its input schema in canonical JSON. Servers take descriptions from the
manifest and stop if any hash differs. After an intentional edit:

```bash
uv run python -m cohortex_mcp_common.manifest --write   # rewrite hashes (review the diff)
uv run python -m cohortex_mcp_common.manifest --check   # CI: exit 1 if stale
```

**4 KB cap with lossless paging (FR-TOOL-6).** A list tool first builds its complete, bounded row
list, for example ≤ 100 models or ≤ 500 failed drives. `finalize` then measures the envelope with an
empty list and worst-case values for `page`, `next_page` and timestamps. Rows are packed in order
into pages that fit the remaining budget, with an optional row limit (25 for `failed_drives`).
`page` picks one page. `next_page` is the next index, or `null` on the last page. `truncated` is
true when more pages follow or the tool's row limit removed rows. The split depends only on the rows
and the non-`page` arguments, so walking `next_page` returns every row exactly once. A non-list
result over 4 KB, or a single row over the budget, is a `too_large` error.

**Transports.** `build_http_app` serves streamable HTTP at `/mcp` (stateless, JSON responses) and
`GET /healthz`. `serve_stdio` serves stdio. The SDK negotiates protocol 2026-07-28 with current
clients and still answers older handshake-era clients such as earlier Inspector builds.

**Why the pytest plugin.** The repo has a top-level `mcp/` folder. Under pytest's
`--import-mode=importlib`, test modules are named after their path (`mcp.mcp-stats.tests...`). If
the SDK is not imported yet, pytest registers a placeholder `mcp` package for that folder, which
hides the real SDK. The plugin, auto-loaded through the `pytest11` entry point, imports the SDK
first.
