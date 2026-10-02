# ADR-006: LangGraph orchestrates both agent modes behind one interface

- **Status:** Proposed
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

LangGraph orchestrates both agent modes behind one interface.

## Why

Explicit state graph, checkpoints, and an easy A/B comparison of single-agent and orchestrated modes.

## Rejected alternative

A custom loop, or a higher-level multi-agent framework.

## Consequences

MCP tools are bridged into LangGraph by an in-repo adapter (ADR-012).
