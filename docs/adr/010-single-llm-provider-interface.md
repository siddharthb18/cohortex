# ADR-010: Model access goes through one provider interface configured by environment

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Model access goes through one provider interface configured by environment.

## Why

Swap Anthropic, OpenAI or a local model without code changes, and pin the model per run.

## Rejected alternative

Direct SDK calls inside graph nodes.

## Consequences

Token counting, retries, spend cap and recording/replay for CI all live in one place.
