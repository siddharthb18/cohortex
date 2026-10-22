/**
 * API types for agent-service and fleet-api.
 *
 * Written by hand from docs/specs/contracts.md §4 (REST tables) and §6 (Report/Claim/NumberRef),
 * and docs/implementation-notes.md §5 (fleet-api semantics) and §7 (agent-service details).
 * When contracts/openapi/*.yaml exist, replace this file with types generated from them
 * (ERS §3: "types generated from contracts/openapi").
 *
 * Shapes the specs leave open are marked "UNSPECIFIED" and are read defensively by
 * src/api/normalize.ts.
 */

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

export type Source = 'backblaze' | 'alibaba';
export type Media = 'hdd' | 'ssd';
export type Granularity = 'quarter' | 'month';
/** ISO 8601 date, e.g. 2026-04-01. */
export type IsoDate = string;
/** ISO 8601 timestamp. */
export type IsoDateTime = string;

/** RFC 9457 problem details (FR-API-7). */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
}

/** Paged list shape from implementation-notes §5. */
export interface Paged<T> {
  items: T[];
  page: number;
  size: number;
  total: number;
}

// ---------------------------------------------------------------------------
// Agent schemas (contracts §6)
// ---------------------------------------------------------------------------

/** Pydantic `Scope` inside Plan/Report. */
export interface Scope {
  source: Source | null;
  models: string[];
  date_from: IsoDate | null;
  date_to: IsoDate | null;
}

/** Request scope for POST /v1/investigations (contracts §4 table: `{source, models[], from, to}`). */
export interface ScopeRequest {
  source?: Source;
  models?: string[];
  from?: IsoDate;
  to?: IsoDate;
}

export interface Task {
  id: string;
  kind: 'data' | 'literature' | 'stats';
  goal: string;
  depends_on: string[];
}

export interface Plan {
  restated_question: string;
  scope: Scope;
  tasks: Task[];
}

export type NumberUnit = 'pct' | 'count' | 'drive_days' | 'days' | 'ratio' | 'p_value' | 'raw';

export interface NumberRef {
  value: number;
  unit: NumberUnit;
  evidence_id: string;
  /** JSON path into the evidence envelope's `data`, e.g. `series[0].afr_pct`. */
  field: string;
}

export interface Claim {
  text: string;
  numbers: NumberRef[];
  evidence_ids: string[];
  passage_ids: string[];
  status: 'supported' | 'unsupported';
}

export type Confidence = 'low' | 'medium' | 'high';

export interface Hypothesis {
  statement: string;
  support: Claim[];
  confidence: Confidence;
  how_to_confirm: string;
}

export type InvestigationMode = 'single' | 'orchestrated';

export interface Report {
  question: string;
  scope: Scope;
  summary: Claim[];
  findings: Claim[];
  hypotheses: Hypothesis[];
  recommended_actions: string[];
  limitations: string[];
  unverified: Claim[];
  mode: InvestigationMode;
  model_id: string;
  prompt_hashes: Record<string, string>;
}

// ---------------------------------------------------------------------------
// agent-service REST (contracts §4, implementation-notes §7)
// ---------------------------------------------------------------------------

export type InvestigationStatus =
  'queued' | 'running' | 'completed' | 'failed' | 'budget_exceeded' | 'refused';

export interface CreateInvestigationRequest {
  question: string;
  scope?: ScopeRequest;
  mode?: InvestigationMode;
}

/** `202 {"id", "status": "queued"}` */
export interface CreateInvestigationResponse {
  id: string;
  status: InvestigationStatus;
}

/** GET /v1/investigations/{id} */
export interface InvestigationDetail {
  id: string;
  question: string;
  scope: ScopeRequest | Scope | null;
  mode: InvestigationMode;
  status: InvestigationStatus;
  llm_model: string;
  started_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | string | null;
  report: Report | null;
  markdown: string | null;
}

/**
 * One row of GET /v1/investigations?limit=20 (open question 18).
 * UNSPECIFIED: the row shape. We assume a subset of InvestigationDetail and accept either a
 * bare array or `{items: [...]}`.
 */
export type InvestigationSummary = Pick<
  InvestigationDetail,
  'id' | 'question' | 'mode' | 'status' | 'started_at'
> &
  Partial<Pick<InvestigationDetail, 'finished_at' | 'llm_model' | 'tokens_in' | 'tokens_out'>>;

/** Step kinds from the `investigation_step.kind` CHECK constraint. */
export type StepKind = 'plan' | 'tool_call' | 'draft' | 'check' | 'report' | 'error';

export interface PlanPayload {
  plan: Plan;
}
export interface ToolCallPayload {
  tool: string;
  args: Record<string, unknown>;
  evidence_id: string;
  ok: boolean;
  summary: string;
}
export interface DraftPayload {
  claims: Claim[];
}
export interface CheckPayload {
  supported: number;
  unsupported: number;
  notes: string[];
}
export interface ReportStepPayload {
  status: InvestigationStatus;
}
export interface ErrorStepPayload {
  message: string;
}

interface StepBase<K extends StepKind, P> {
  seq: number;
  /** planner, worker:data, drafter, checker, reporter, agent */
  node: string;
  kind: K;
  payload: P;
  started_at: IsoDateTime;
  ended_at: IsoDateTime | null;
}

/** SSE `event: step` data. */
export type Step =
  | StepBase<'plan', PlanPayload>
  | StepBase<'tool_call', ToolCallPayload>
  | StepBase<'draft', DraftPayload>
  | StepBase<'check', CheckPayload>
  | StepBase<'report', ReportStepPayload>
  | StepBase<'error', ErrorStepPayload>;

/** SSE terminal `event: report` data. */
export interface ReportEventData {
  status: InvestigationStatus;
  report: Report | null;
  markdown: string | null;
}

/** SSE terminal `event: error` data. */
export interface ErrorEventData {
  status: InvestigationStatus;
  message: string;
}

/** contracts §5 result envelope (every tool). */
export interface EvidenceEnvelope {
  evidence_id: string;
  tool: string;
  args: Record<string, unknown>;
  source: string;
  generated_at: IsoDateTime;
  data: unknown;
  truncated: boolean;
  next_page: number | null;
}

/** GET /v1/investigations/{id}/evidence/{evidence_id} */
export interface EvidenceRecord {
  evidence_id: string;
  tool: string;
  args: Record<string, unknown>;
  /** The full result envelope. */
  result: EvidenceEnvelope;
  created_at: IsoDateTime;
}

/**
 * One row of GET /v1/alerts/suggested: "open alerts with a suggested question each".
 * UNSPECIFIED: exact row shape. We assume the `alerts.cohort.v1` payload (contracts §3) plus
 * `source`, optional `opened_at` and `suggested_question`; array or `{items}` accepted.
 */
export interface SuggestedAlert {
  alert_id: string;
  source?: Source;
  model: string;
  window_start: IsoDate;
  window_end: IsoDate;
  baseline_afr: number;
  current_afr: number;
  rate_ratio: number;
  p_value: number;
  status: 'open' | 'resolved';
  opened_at?: IsoDateTime;
  suggested_question: string;
}

/**
 * GET /v1/evals/latest: the latest `eval_run` row as JSON (contracts §2 DDL), or 404.
 * UNSPECIFIED: the `metrics` object. The UI reads keys `M1`..`M10` (see src/lib/evals.ts).
 */
export interface EvalRun {
  id: string;
  started_at: IsoDateTime;
  git_sha: string;
  golden_version: string;
  mode: string;
  llm_model: string;
  recorded: boolean;
  metrics: Record<string, unknown>;
  passed: boolean;
}

// ---------------------------------------------------------------------------
// fleet-api REST (contracts §4, implementation-notes §5)
// ---------------------------------------------------------------------------

export interface AfrPoint {
  /** `YYYYQn` or `YYYY-MM` */
  period: string;
  drive_days: number;
  failures: number;
  afr_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
}

/** GET /v1/cohorts/{source}/{model}/afr */
export interface CohortAfrResponse {
  source: Source;
  model: string;
  series: AfrPoint[];
  method: 'exact_poisson_95';
  generated_at: IsoDateTime;
}

/** One ranked row of GET /v1/cohorts/compare. */
export interface CohortCompareRow {
  model: string;
  drive_days: number;
  failures: number;
  afr_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
  rate_ratio_vs_fleet: number;
}

/**
 * GET /v1/cohorts/compare. UNSPECIFIED: the wrapper key. We expect
 * `{source, from, to, cohorts: [...], method, generated_at}` and also accept `items`, `rows`
 * or a bare array (see normalize.ts).
 */
export interface CohortCompareResponse {
  source?: Source;
  from?: IsoDate;
  to?: IsoDate;
  cohorts: CohortCompareRow[];
  method?: 'exact_poisson_95';
  generated_at?: IsoDateTime;
}

/** GET /v1/fleet/summary: "Fleet totals: drives, drive-days, failures, AFR with CI". */
export interface FleetSummary {
  source: Source;
  from: IsoDate;
  to: IsoDate;
  drives: number;
  drive_days: number;
  failures: number;
  afr_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
  method: 'exact_poisson_95';
  generated_at: IsoDateTime;
}

export interface SmartTrendPoint {
  period: string;
  p50: number | null;
  p95: number | null;
  nonzero_share: number | null;
  n_drives: number;
}

/** GET /v1/cohorts/{source}/{model}/smart-trend (P2). Wrapper assumed like the AFR response. */
export interface SmartTrendResponse {
  source: Source;
  model: string;
  attr: number;
  series: SmartTrendPoint[];
  generated_at?: IsoDateTime;
}

/** One row of GET /v1/cohorts/{source}/{model}/failed-drives (paged, implementation-notes §5). */
export interface FailedDrive {
  drive_id: string;
  failed_on: IsoDate;
  age_days: number;
  /** `{attr: raw_value}` on `failed_on`. */
  last_smart: Record<string, number | null>;
}

export type FailedDrivesResponse = Paged<FailedDrive>;
