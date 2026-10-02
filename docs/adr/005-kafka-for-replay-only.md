# ADR-005: Kafka carries replay events and alerts only; backfill uses bulk `COPY`

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Kafka carries replay events and alerts only; backfill uses bulk `COPY`.

## Why

Streaming where it adds realism, bulk loading where it is cheaper and simpler.

## Rejected alternative

All ingest through Kafka.

## Consequences

Two ingest paths (batch and stream) share the same serving tables and must agree.
