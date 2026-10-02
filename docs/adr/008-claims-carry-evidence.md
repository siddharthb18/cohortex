# ADR-008: Every claim carries `evidence_ids`; numbers are checked by code before any LLM check

- **Status:** Proposed
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Every claim carries `evidence_ids`; numbers are checked by code before any LLM check.

## Why

Cheap, deterministic grounding; LLM judgment only where code cannot decide.

## Rejected alternative

LLM-only faithfulness checking.

## Consequences

The report schema requires structured `NumberRef`s, which makes drafting prompts stricter.
