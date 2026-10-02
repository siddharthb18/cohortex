# Cohortex

**Agentic reliability investigations over public HDD and SSD fleet telemetry, where every number in a
report is checked against independently computed SQL.**

Ask "why did this drive model's failure rate jump last quarter?" Cohortex plans the investigation,
gathers evidence through typed, read-only tools (MCP), checks every numeric claim against the data
it came from, and writes a cited report. An evaluation harness grades those reports in CI against
truth computed on a separate data path.

> **Status:** WP-00, repository bootstrap. Nothing runs end to end yet. See the
> [build plan](docs/specs/build-plan.md) for what comes next.

## Architecture at a glance

| Layer | Components |
| --- | --- |
| Data | Backblaze Drive Stats (HDD), Alibaba SSD SMART logs → Parquet raw layer (DuckDB) + Postgres/pgvector serving store |
| Platform (Java) | `fleet-api` (Spring Boot REST), `stream-ingest` (Kafka replay) |
| Tools (Python) | MCP servers `mcp-fleet`, `mcp-stats`, `mcp-docs` (protocol 2026-07-28) |
| Agent (Python) | `agent-service`: LangGraph, single-agent and orchestrator-workers modes, evidence ledger, claim checker |
| Quality | `evals/harness`: golden sets, code graders, validated LLM judge, CI gate |
| Ops | OpenTelemetry → Jaeger, Prometheus, Docker Compose, Kubernetes + Helm, Terraform |

Full detail: [design document](docs/specs/design.md).

## Quick start (local)

Requirements: Docker (Docker Desktop on Windows with WSL2), [uv](https://docs.astral.sh/uv/),
Node 22, and a JDK 17+ to launch Gradle (Gradle then downloads JDK 25 itself).
Models cost nothing (ADR-013): put a free [Groq](https://console.groq.com) key in `.env`, or run
[Ollama](https://ollama.com) locally with `ollama pull gpt-oss:20b`.

```bash
cp .env.example .env
make up          # Postgres+pgvector, Kafka (KRaft), OTel Collector, Jaeger
make test        # Python and Java checks
make down
```

Jaeger UI: http://localhost:16686

## Documentation

- [Specification overview and originality](docs/specs/overview.md)
- [Design](docs/specs/design.md) · [SRS](docs/specs/SRS.md) · [ERS](docs/specs/ERS.md)
- [Contracts](docs/specs/contracts.md) · [Evaluation](docs/specs/evaluation.md) · [Build plan](docs/specs/build-plan.md)
- [Architecture decisions](docs/adr/README.md) · [Pinned versions](docs/versions.md) · [Open questions](docs/open-questions.md)

## How this was built

Claude agents wrote much of this code from the specifications in `docs/specs/`. Siddharth Bhatt
designed the system, wrote and reviewed the specifications, accepted the architecture decisions,
reviewed every change, labeled the evaluation data, and ran the error analysis. Human-owned work is
listed in the [build plan](docs/specs/build-plan.md#3-human-owned-tasks-and-explain-back-checklist).

## Related work

- Backblaze's [ai-agent-demo](https://github.com/backblaze-b2-samples/ai-agent-demo) answers questions
  over Drive Stats with model-written SQL. Cohortex does not let the model write SQL; it uses typed tools
  and grades its answers against independent truth.
- [KORAL](https://arxiv.org/abs/2602.10246) (IPDPS 2026) grounds LLM analysis of SSD telemetry in knowledge
  graphs. Cohortex adapts its faithfulness-precision idea for one evaluation metric.

## Data attribution

- **Backblaze Drive Stats**: hard drive data and statistics courtesy of
  [Backblaze](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data). The data is free and
  may not be sold.
- **Alibaba SSD SMART logs**: from F. Xu, S. Han, P. P. C. Lee, et al., *General Feature Selection for Failure
  Prediction in Large-scale SSD Deployment*, DSN 2021
  ([dataset](https://github.com/alibaba-edu/dcbrain/tree/master/ssd_smart_logs)).

Raw datasets are never committed; only small attributed fixtures live in `data/fixtures/`.

## License

[MIT](LICENSE) for the code. The datasets keep their own terms (see above).
