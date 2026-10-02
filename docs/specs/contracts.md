# Cohortex — Data, API & Tool Contracts

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes.

## 1. Source datasets and raw-layer schema

Both sources are public and attributed. Field lists below marked *verify* come from documentation summaries; WP-01 must confirm them against the official schema files before writing parsers, and record any difference in `docs/open-questions.md`.

**Backblaze Drive Stats** ([data page](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data))

- Quarterly ZIPs at `https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_Q{n}_{yyyy}.zip`; each holds one `YYYY-MM-DD.csv` per day, one row per operational drive. Q2 2026 is 2.1 GB zipped, 11.7 GB unzipped, 91 files.
- Current schema: `Drive_Stats_Schema_Current.csv`; changes since 2018: `Drive_Stats_Schema_2018_Onward.csv` (same host). Schemas change between quarters, so the parser reads the schema file every run.
- Non-SMART columns (*verify*): `date`, `serial_number`, `model`, `capacity_bytes`, `failure`, and in recent years `datacenter`, `cluster_id`, `vault_id`, `pod_id`, `pod_slot_num`, `is_legacy_format`. SMART columns follow `smart_{id}_normalized` and `smart_{id}_raw`.
- `failure` is 1 on a drive's last operational day before it fails, else 0.
- Also published as an Apache Iceberg table (bucket `drivestats-iceberg`, prefix `drivestats`, endpoint `https://s3.us-west-004.backblazeb2.com`) with read-only keys listed on the data page.
- Terms: cite Backblaze as the source; the data may not be sold.

**Alibaba SSD SMART logs** ([readme](https://github.com/alibaba-edu/dcbrain/tree/master/ssd_smart_logs); download via Alibaba Tianchi, dataset 95044)

- Daily SMART data and failures for six SSD models, January 1, 2018 to December 31, 2019; over 500,000 drives.
- SMART files are named by sampling date `yyyymmdd`; fields include a drive identifier, model, and `n_{id}` (normalized) and `r_{id}` (raw) per attribute (*verify exact names*).
- Failure labels give each failed drive's `failure_time` (*verify*).
- Terms: cite *General Feature Selection for Failure Prediction in Large-scale SSD Deployment* (DSN 2021).

**Raw-layer views (DuckDB)**

| View | Columns | Notes |
| --- | --- | --- |
| `raw_backblaze_day` | All source columns, lower-cased, plus `schema_version` | Partitioned by year, quarter |
| `raw_alibaba_day` | All source columns plus `source_file_date` | One row per drive per day |
| `raw_alibaba_failure` | Drive ID, model, `failure_time` | Joined to derive `failed_on` |
| `drive_day` | `source`, `day`, `drive_id`, `model`, `capacity_bytes`, `media` (hdd or ssd), `failure` | Unified view; every truth SQL query starts here |

**SMART attributes kept in serving tables**

- HDD: 5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242.
- SSD (Alibaba raw values): 5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199.
- Changing this list requires an ADR, because golden-set truth for SMART questions depends on it.

## 2. Serving database DDL

This is the target schema for Flyway migration `V1__init.sql`. `${embedding_dim}` is a Flyway placeholder set from `EMBEDDING_DIM`. Later changes are new migrations, never edits to `V1`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE ingest_run (
  id            uuid PRIMARY KEY,
  source        text NOT NULL CHECK (source IN ('backblaze','alibaba')),
  period        text NOT NULL,                 -- e.g. 2026Q2
  source_url    text NOT NULL,
  bytes         bigint NOT NULL,
  sha256        text NOT NULL,
  schema_version text,
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  status        text NOT NULL CHECK (status IN ('running','succeeded','failed')),
  reconciliation jsonb
);

CREATE TABLE drive_model (
  id             serial PRIMARY KEY,
  source         text NOT NULL,
  model          text NOT NULL,
  media          text NOT NULL CHECK (media IN ('hdd','ssd')),
  capacity_bytes bigint,
  UNIQUE (source, model)
);

CREATE TABLE drive (
  source     text NOT NULL,
  drive_id   text NOT NULL,                    -- serial number or Alibaba disk id
  model_id   int  NOT NULL REFERENCES drive_model(id),
  first_seen date NOT NULL,
  last_seen  date NOT NULL,
  failed_on  date,
  sampled    boolean NOT NULL DEFAULT false,   -- in the 1% hash sample
  PRIMARY KEY (source, drive_id)
);
CREATE INDEX drive_model_failed ON drive (model_id, failed_on);

CREATE TABLE cohort_daily (
  model_id    int  NOT NULL REFERENCES drive_model(id),
  day         date NOT NULL,
  drive_count int  NOT NULL CHECK (drive_count >= 0),
  failures    int  NOT NULL CHECK (failures >= 0),
  PRIMARY KEY (model_id, day)
);

CREATE TABLE smart_daily (
  source     text     NOT NULL,
  drive_id   text     NOT NULL,
  day        date     NOT NULL,
  attr       smallint NOT NULL,
  raw_value  double precision,
  normalized smallint,
  PRIMARY KEY (source, drive_id, day, attr)
) PARTITION BY RANGE (day);                    -- monthly partitions created by ingest

CREATE TABLE alert (
  id            uuid PRIMARY KEY,
  model_id      int NOT NULL REFERENCES drive_model(id),
  opened_at     timestamptz NOT NULL,
  window_start  date NOT NULL,
  window_end    date NOT NULL,
  baseline_afr  double precision NOT NULL,
  current_afr   double precision NOT NULL,
  rate_ratio    double precision NOT NULL,
  p_value       double precision NOT NULL,
  status        text NOT NULL CHECK (status IN ('open','resolved')),
  resolved_at   timestamptz
);
CREATE UNIQUE INDEX one_open_alert ON alert (model_id) WHERE status = 'open';

CREATE TABLE investigation (
  id            uuid PRIMARY KEY,
  question      text NOT NULL,
  scope         jsonb,
  mode          text NOT NULL CHECK (mode IN ('single','orchestrated')),
  status        text NOT NULL CHECK (status IN ('queued','running','completed','failed','budget_exceeded','refused')),
  llm_model     text NOT NULL,
  prompt_hashes jsonb NOT NULL,
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  tokens_in     int, tokens_out int,
  cost_usd      numeric(10,4),
  report        jsonb,
  eval_run_id   uuid
);

CREATE TABLE investigation_step (
  id               bigserial PRIMARY KEY,
  investigation_id uuid NOT NULL REFERENCES investigation(id),
  seq              int  NOT NULL,
  node             text NOT NULL,             -- planner, worker:data, drafter, checker, reporter, agent
  kind             text NOT NULL CHECK (kind IN ('plan','tool_call','draft','check','report','error')),
  payload          jsonb NOT NULL,
  started_at       timestamptz NOT NULL,
  ended_at         timestamptz,
  UNIQUE (investigation_id, seq)
);

CREATE TABLE evidence (
  evidence_id      text PRIMARY KEY,          -- 'ev_' + first 16 hex of sha256(investigation_id|seq|tool|canonical_args)
  investigation_id uuid NOT NULL REFERENCES investigation(id),
  tool_name        text NOT NULL,
  args             jsonb NOT NULL,
  result           jsonb NOT NULL,
  created_at       timestamptz NOT NULL
);

CREATE TABLE claim (
  id               bigserial PRIMARY KEY,
  investigation_id uuid NOT NULL REFERENCES investigation(id),
  section          text NOT NULL,
  text             text NOT NULL,
  numbers          jsonb NOT NULL DEFAULT '[]',   -- [{value, unit, evidence_id, field}]
  evidence_ids     text[] NOT NULL DEFAULT '{}',
  status           text NOT NULL CHECK (status IN ('supported','unsupported')),
  checker_notes    text
);

CREATE TABLE document (
  id           serial PRIMARY KEY,
  title        text NOT NULL,
  url          text NOT NULL UNIQUE,
  publisher    text,
  published_on date,
  access_basis text NOT NULL,                  -- e.g. 'open access', 'public blog post'
  sha256       text NOT NULL
);

CREATE TABLE chunk (
  id             bigserial PRIMARY KEY,
  document_id    int NOT NULL REFERENCES document(id),
  ordinal        int NOT NULL,
  section_anchor text,
  text           text NOT NULL,
  tokens         int  NOT NULL,
  embedding      vector(${embedding_dim}) NOT NULL,
  tsv            tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX chunk_tsv ON chunk USING gin (tsv);
CREATE INDEX chunk_vec ON chunk USING hnsw (embedding vector_cosine_ops);

CREATE TABLE eval_run (
  id             uuid PRIMARY KEY,
  started_at     timestamptz NOT NULL,
  git_sha        text NOT NULL,
  golden_version text NOT NULL,
  mode           text NOT NULL,
  llm_model      text NOT NULL,
  recorded       boolean NOT NULL,             -- true when run on recorded responses
  metrics        jsonb NOT NULL,
  passed         boolean NOT NULL
);

CREATE TABLE eval_case_result (
  eval_run_id      uuid NOT NULL REFERENCES eval_run(id),
  case_id          text NOT NULL,
  investigation_id uuid REFERENCES investigation(id),
  passed           boolean NOT NULL,
  scores           jsonb NOT NULL,
  PRIMARY KEY (eval_run_id, case_id)
);

CREATE TABLE human_label (
  id               bigserial PRIMARY KEY,
  investigation_id uuid NOT NULL REFERENCES investigation(id),
  step_seq         int,
  label            text NOT NULL,              -- open code, later mapped to the taxonomy
  note             text,
  labeler          text NOT NULL,
  created_at       timestamptz NOT NULL
);

CREATE TABLE llm_spend (
  month date PRIMARY KEY,
  usd   numeric(10,4) NOT NULL DEFAULT 0
);
```

## 3. Kafka topics and event schemas

Events are JSON with a common envelope, validated against `contracts/events/*.schema.json` on produce and consume. Version lives in the topic name; a breaking change means a new topic.

| Topic | Key | Partitions | Retention | Producer → consumers |
| --- | --- | --- | --- | --- |
| `cohort.day.v1` | `source:model` | 6 | 7 days | stream-ingest replay → stream-ingest consumer |
| `drive.failure.v1` | `source:drive_id` | 6 | 7 days | replay → consumer |
| `drive.snapshot.v1` | `source:drive_id` | 12 | 3 days | replay → consumer (sampled drives only) |
| `fleet.day.closed.v1` | `source` | 1 | 7 days | consumer → analytics-worker |
| `alerts.cohort.v1` | `source:model` | 3 | 30 days | analytics-worker → agent-service (suggested investigations), web-ui via API |

**Common envelope**

```json
{
  "event_id": "01J9Z6X3K8...",
  "event_type": "cohort.day.v1",
  "occurred_on": "2026-04-15",
  "produced_at": "2026-10-02T16:20:11Z",
  "source": "backblaze",
  "trace_parent": "00-<trace-id>-<span-id>-01",
  "payload": { }
}
```

`event_id` is a ULID; consumers store processed IDs for 7 days and skip duplicates (FR-ING-8). `trace_parent` carries W3C trace context so replay and analytics join the same traces.

**Payloads**

| Event | Payload fields |
| --- | --- |
| `cohort.day.v1` | `model`, `media`, `capacity_bytes`, `drive_count`, `failures` |
| `drive.failure.v1` | `drive_id`, `model`, `failed_on`, `first_seen`, `smart` (object of kept attributes on the last day) |
| `drive.snapshot.v1` | `drive_id`, `model`, `smart` (object of kept attributes) |
| `fleet.day.closed.v1` | `day`, `models_updated`, `drive_days`, `failures` |
| `alerts.cohort.v1` | `alert_id`, `model`, `window_start`, `window_end`, `baseline_afr`, `current_afr`, `rate_ratio`, `p_value`, `status` |

## 4. REST APIs

The OpenAPI files in `contracts/openapi/` are generated from this table and then become the source of truth. All paths are versioned under `/v1`; dates are ISO 8601; errors are RFC 9457 `application/problem+json`.

**fleet-api (Java)**

| Method and path | Parameters | Returns |
| --- | --- | --- |
| `GET /v1/models` | `source?`, `media?`, `page`, `size` | Models with `id`, `source`, `model`, `media`, `capacity_bytes`, `drive_count` |
| `GET /v1/cohorts/{source}/{model}/afr` | `from`, `to` (dates), `granularity` = `quarter` or `month` | Series of `{period, drive_days, failures, afr_pct, ci_low_pct, ci_high_pct}` |
| `GET /v1/cohorts/compare` | `source`, `from`, `to`, `min_drives` (default 60), `limit` (≤ 50) | Ranked `{model, drive_days, failures, afr_pct, ci_low_pct, ci_high_pct, rate_ratio_vs_fleet}` |
| `GET /v1/cohorts/{source}/{model}/smart-trend` | `attr`, `from`, `to`, `granularity` | Series of `{period, p50, p95, nonzero_share, n_drives}` from the sampled set |
| `GET /v1/cohorts/{source}/{model}/failed-drives` | `from`, `to`, `page`, `size` | `{drive_id, failed_on, age_days, last_smart}` |
| `GET /v1/fleet/summary` | `source`, `from`, `to` | Fleet totals: drives, drive-days, failures, AFR with CI |
| `GET /v1/alerts` | `status?`, `source?` | Alerts as in the DDL |
| `GET /actuator/health` | — | Liveness and readiness |

Example `GET /v1/cohorts/backblaze/ST12000NM000J/afr?from=2026-04-01&to=2026-06-30&granularity=quarter` response shape:

```json
{
  "source": "backblaze",
  "model": "ST12000NM000J",
  "series": [
    {"period": "2026Q2", "drive_days": 98189, "failures": 0,
     "afr_pct": 0.0, "ci_low_pct": 0.0, "ci_high_pct": 1.37}
  ],
  "method": "exact_poisson_95",
  "generated_at": "2026-10-02T16:20:11Z"
}
```

The numbers above illustrate the shape only; tests must use fixture truth.

**agent-service (Python)**

| Method and path | Body or parameters | Returns |
| --- | --- | --- |
| `POST /v1/investigations` | `{question, scope?: {source, models[], from, to}, mode?: "single" or "orchestrated"}` | `202 {id, status}` |
| `GET /v1/investigations/{id}` | — | Status, timings, tokens, cost, report (when complete) |
| `GET /v1/investigations/{id}/events` | SSE | `step` events (plan, tool_call, draft, check), then `report` or `error` |
| `GET /v1/investigations/{id}/evidence/{evidence_id}` | — | Tool name, arguments, result |
| `GET /v1/alerts/suggested` | — | Open alerts with a suggested question each |
| `GET /v1/evals/latest` | `mode?` | Latest eval run metrics and pass or fail |
| `GET /healthz`, `GET /readyz` | — | Liveness and readiness |

Owner-only routes require `Authorization: Bearer <ADMIN_TOKEN>`; in public mode, `POST /v1/investigations` is rate-limited and forced to the cheaper mode chosen by config.

## 5. MCP tool contracts

Three servers, eleven tools, all read-only and parameterized (ADR-001). Every result is wrapped in the same evidence envelope so the agent, the checker and the UI handle all tools alike. Descriptions are written once in `contracts/tools/manifest.json`, hashed, and checked at server start (FR-TOOL-5).

**Result envelope (every tool)**

```json
{
  "evidence_id": "ev_3f9a1c0b7d2e4a51",
  "tool": "fleet.cohort_afr",
  "args": {"source": "backblaze", "model": "ST12000NM000J", "from": "2026-04-01", "to": "2026-06-30"},
  "source": "fleet-api /v1/cohorts/{source}/{model}/afr",
  "generated_at": "2026-10-02T16:20:11Z",
  "data": { },
  "truncated": false,
  "next_page": null
}
```

`evidence_id` is assigned by `agent-service` when it records the call; servers return it empty and the ledger fills it, so IDs stay unique per investigation.

| Server · tool | Inputs (all required unless marked ?) | `data` returned | Limits |
| --- | --- | --- | --- |
| fleet · `list_models` | `source`, `media?`, `min_drives?` | `[{model, media, capacity_bytes, drive_count}]` | ≤ 100 rows |
| fleet · `cohort_afr` | `source`, `model`, `from`, `to`, `granularity?` | AFR series with 95% CI | Window ≤ 8 quarters |
| fleet · `compare_cohorts` | `source`, `from`, `to`, `min_drives?`, `limit?` | Ranked cohorts with rate ratio vs fleet | `limit` ≤ 20 |
| fleet · `fleet_summary` | `source`, `from`, `to` | Fleet totals with CI | — |
| fleet · `smart_trend` | `source`, `model`, `attr` (enum of kept attributes), `from`, `to` | p50, p95, non-zero share by period | Sampled drives only; result states the sample size |
| fleet · `failed_drives` | `source`, `model`, `from`, `to`, `page?` | Failures with age and last SMART values | 25 per page |
| stats · `afr_ci` | `failures` (int ≥ 0), `drive_days` (int > 0), `confidence?` (default 0.95) | `{afr_pct, ci_low_pct, ci_high_pct, method}` | Pure function |
| stats · `compare_rates` | `failures_a`, `drive_days_a`, `failures_b`, `drive_days_b` | `{rate_ratio, ci_low, ci_high, p_value, method}` (exact conditional binomial test) | Pure function |
| stats · `change_point` | `series` of `{period, failures, drive_days}` (≤ 60 points) | Most likely change period with likelihood-ratio statistic and p-value | Pure function |
| docs · `search` | `query` (≤ 300 chars), `k?` (≤ 8) | `[{passage_id, title, url, section, snippet ≤ 300 chars, score}]` | Hybrid RRF |
| docs · `get_passage` | `passage_id` | `{passage_id, title, url, section, text ≤ 1,200 chars}` | — |

Example input schema, `fleet.cohort_afr`:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["source", "model", "from", "to"],
  "properties": {
    "source": {"type": "string", "enum": ["backblaze", "alibaba"]},
    "model": {"type": "string", "pattern": "^[A-Za-z0-9_.\\- ]{1,64}$"},
    "from": {"type": "string", "format": "date"},
    "to": {"type": "string", "format": "date"},
    "granularity": {"type": "string", "enum": ["quarter", "month"], "default": "quarter"}
  }
}
```

**Tool descriptions are part of the contract.** Each states what the tool returns, its units (percent for AFR), its limits, and one example call. They contain no instructions to the model beyond describing the tool.

## 6. Agent state, claim and report schemas

These Pydantic models are the contract between graph nodes and the source of `contracts/report/report.schema.json`. Both agent modes produce the same `Report`.

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

class Scope(BaseModel):
    source: Literal["backblaze", "alibaba"] | None = None
    models: list[str] = Field(default_factory=list, max_length=10)
    date_from: date | None = None
    date_to: date | None = None

class Task(BaseModel):
    id: str                                  # t1..t6
    kind: Literal["data", "literature", "stats"]
    goal: str = Field(max_length=300)
    depends_on: list[str] = Field(default_factory=list)

class Plan(BaseModel):
    restated_question: str
    scope: Scope
    tasks: list[Task] = Field(min_length=1, max_length=6)

class NumberRef(BaseModel):
    value: float
    unit: Literal["pct", "count", "drive_days", "days", "ratio", "p_value", "raw"]
    evidence_id: str
    field: str                               # JSON path in the evidence data, e.g. series[0].afr_pct

class Claim(BaseModel):
    text: str = Field(max_length=500)
    numbers: list[NumberRef] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    status: Literal["supported", "unsupported"] = "unsupported"

class Hypothesis(BaseModel):
    statement: str
    support: list[Claim]
    confidence: Literal["low", "medium", "high"]
    how_to_confirm: str                      # what data or test would settle it

class Report(BaseModel):
    question: str
    scope: Scope
    summary: list[Claim] = Field(max_length=5)      # supported claims only
    findings: list[Claim]
    hypotheses: list[Hypothesis] = Field(max_length=4)
    recommended_actions: list[str] = Field(max_length=5)
    limitations: list[str]                   # includes triggered dataset caveats
    unverified: list[Claim]                  # failed the evidence check
    mode: Literal["single", "orchestrated"]
    model_id: str
    prompt_hashes: dict[str, str]

class InvestigationState(BaseModel):          # LangGraph state
    investigation_id: str
    question: str
    plan: Plan | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    draft: list[Claim] = Field(default_factory=list)
    revisions: int = 0                       # max 2
    tool_calls: int = 0                      # max 20
    input_tokens: int = 0                    # max 150_000
    report: Report | None = None
    status: Literal["running", "completed", "failed", "budget_exceeded", "refused"] = "running"
```

**Numeric check rule (FR-AGT-6).** For each `NumberRef`, read `field` from the referenced evidence; the claim passes when the values match within 0.5% relative or 0.01 absolute for percentages, and exactly for counts. Units must match the field's declared unit.

**Dataset caveats the reporter must add to `limitations` when triggered:**

- Cohort has fewer than 60 drives or fewer than 3 failures: AFR is unstable; cite the interval.
- Backblaze data: drives that fail on their first day are not captured.
- SMART-based statements: many failures show no prior SMART signal.
- SMART trends come from a 1% sample plus failed drives, not the full cohort.
- Alibaba data covers 2018–2019 only.
