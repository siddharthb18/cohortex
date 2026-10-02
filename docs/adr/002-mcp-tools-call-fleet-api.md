# ADR-002: MCP data tools call `fleet-api`, never the database

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

MCP data tools call `fleet-api`, never the database.

## Why

One owner for data access, validation and limits; the Java API is reusable outside the agent.

## Rejected alternative

MCP tools with their own database connections.

## Consequences

`mcp-fleet` is a thin typed client of `fleet-api`. An extra network hop per tool call, visible in traces.
