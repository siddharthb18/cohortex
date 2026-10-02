# ADR-004: Parquet + DuckDB raw layer is the eval truth source

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Parquet + DuckDB raw layer is the eval truth source.

## Why

Truth computed on an independent path from the serving tables makes grading a real cross-check, not the system grading itself.

## Rejected alternative

Truth computed from Postgres.

## Consequences

Two copies of the data to keep consistent; reconciliation (FR-ING-5) guards the serving copy.
