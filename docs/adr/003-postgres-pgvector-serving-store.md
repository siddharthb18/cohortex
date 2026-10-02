# ADR-003: Postgres + pgvector holds serving data and corpus vectors

- **Status:** Accepted
- **Date:** 2026-10-02
- **Decider:** Siddharth Bhatt (accept or reject by editing the status line)

## Decision

Postgres + pgvector holds serving data and corpus vectors.

## Why

One store to operate; hybrid search can combine full-text and vector ranking in the same database.

## Rejected alternative

A separate vector database.

## Consequences

Corpus size must stay modest (thousands of chunks), which fits this project. HNSW index on `chunk.embedding`.
