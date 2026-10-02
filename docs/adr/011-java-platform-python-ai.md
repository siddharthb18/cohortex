# ADR-011: Java for ingest streaming and the fleet API; Python for analytics, tools, agent and evals

- **Status:** Proposed
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Java for ingest streaming and the fleet API; Python for analytics, tools, agent and evals.

## Why

Plays to existing Java/Spring strength while building Python AI depth.

## Rejected alternative

A single language for everything.

## Consequences

Two toolchains in CI; contracts in `contracts/` keep the boundary explicit.
