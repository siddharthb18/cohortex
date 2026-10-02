# ADR-001: The model never writes SQL; it calls typed, parameterized, read-only tools

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

The model never writes SQL; it calls typed, parameterized, read-only tools.

## Why

Removes injection and wrong-query classes, and separates Cohortex from Backblaze's public text-to-SQL agent demo over the same dataset.

## Rejected alternative

Text-to-SQL with a query checker.

## Consequences

Every data question is answered through a tool with a bounded JSON Schema. New questions need new tool parameters, not new prompts. Tool schemas never accept SQL, URLs or file paths (FR-TOOL-4).
