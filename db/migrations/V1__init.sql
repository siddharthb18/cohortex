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
