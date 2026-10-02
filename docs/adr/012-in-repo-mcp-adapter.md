# ADR-012: Bridge MCP tools into LangGraph with a thin in-repo adapter over the MCP SDK 2.x client

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Bridge MCP tools into LangGraph with a thin in-repo adapter over the MCP SDK 2.x client.

## Why

As of 2026-10-02, the latest `langchain-mcp-adapters` (0.3.2, released 2026-08-06) requires `mcp<2.0.0`, so it cannot be installed next to `mcp` 2.2.0, which the spec requires for protocol revision 2026-07-28. A small adapter (list tools, convert JSON Schemas to tool definitions, call tools, record evidence) is also easier to explain in an interview.

## Rejected alternative

Pin `mcp` 1.x to use `langchain-mcp-adapters` (loses the stateless 2026-07-28 protocol); wait for an adapter release.

## Consequences

About 150–250 lines owned in `services/agent-service`. Revisit if `langchain-mcp-adapters` adds `mcp` 2.x support; switching back is a contained change.
