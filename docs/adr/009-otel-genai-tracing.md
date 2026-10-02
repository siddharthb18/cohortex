# ADR-009: Tracing follows OpenTelemetry GenAI semantic conventions

- **Status:** Proposed
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Tracing follows OpenTelemetry GenAI semantic conventions.

## Why

Vendor-neutral, and the MCP Python SDK 2.x already emits these spans.

## Rejected alternative

A vendor-specific tracing SDK only.

## Consequences

The conventions are still marked Development; the pinned version is recorded in `docs/versions.md`.
