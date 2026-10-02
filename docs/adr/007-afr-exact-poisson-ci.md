# ADR-007: AFR uses Backblaze's formula with exact Poisson 95% intervals

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

AFR uses Backblaze's formula with exact Poisson 95% intervals.

## Why

Matches Backblaze's published reports; intervals expose small-cohort noise instead of hiding it.

## Rejected alternative

Plain AFR without uncertainty.

## Consequences

The interval is implemented in both Java and Python and must agree to 1e-9 (FR-ANA-1).
