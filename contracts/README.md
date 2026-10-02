# Contracts

Single source of truth for cross-boundary interfaces (ERS §2). Generated from [docs/specs/contracts.md](/docs/specs/contracts.md) by the work packages that implement each boundary:

| Directory | Contents | Created in |
| --- | --- | --- |
| `openapi/` | `fleet-api.yaml`, `agent-service.yaml` (OpenAPI 3.1) | WP-04, WP-06 |
| `events/` | Kafka event JSON Schemas | WP-13 |
| `tools/` | MCP tool input/output schemas + `manifest.json` with description hashes | WP-05, WP-10 |
| `report/` | `report.schema.json` generated from the Pydantic `Report` model | WP-06 |
