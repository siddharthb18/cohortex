import type { Page, Route } from '@playwright/test';
import type {
  CohortAfrResponse,
  CohortCompareRow,
  EvidenceRecord,
  FailedDrivesResponse,
  FleetSummary,
  InvestigationDetail,
  Report,
  SmartTrendResponse,
  Step,
  SuggestedAlert,
} from '../src/api/types';

/** Small hand-written fixtures that follow contracts §4/§6 and implementation-notes §5/§7. */
export const INVESTIGATION_ID = '9b2e4c1a-7d3f-4e8b-a1c6-5f0d2e9b8a74';
export const QUESTION = 'Why did the failure rate of ST12000NM0008 rise in Q2 2026?';
export const EV_AFR = 'ev_1a2b3c4d5e6f7a8b';
export const EV_RATES = 'ev_9c8d7e6f5a4b3c2d';

const afrData = {
  model: 'ST12000NM0008',
  series: [
    {
      period: '2026Q1',
      drive_days: 1790551,
      failures: 52,
      afr_pct: 1.06,
      ci_low_pct: 0.7917,
      ci_high_pct: 1.39,
    },
    {
      period: '2026Q2',
      drive_days: 1780606,
      failures: 67,
      afr_pct: 1.3712,
      ci_low_pct: 1.0627,
      ci_high_pct: 1.7414,
    },
  ],
  method: 'exact_poisson_95',
};

const evidence: Record<string, EvidenceRecord> = {
  [EV_AFR]: {
    evidence_id: EV_AFR,
    tool: 'fleet.cohort_afr',
    args: { source: 'backblaze', model: 'ST12000NM0008', from: '2026-01-01', to: '2026-06-30' },
    created_at: '2026-10-21T10:00:02Z',
    result: {
      evidence_id: EV_AFR,
      tool: 'fleet.cohort_afr',
      args: { source: 'backblaze', model: 'ST12000NM0008', from: '2026-01-01', to: '2026-06-30' },
      source: 'fleet-api /v1/cohorts/{source}/{model}/afr',
      generated_at: '2026-10-21T10:00:02Z',
      data: afrData,
      truncated: false,
      next_page: null,
    },
  },
  [EV_RATES]: {
    evidence_id: EV_RATES,
    tool: 'stats.compare_rates',
    args: { failures_a: 67, drive_days_a: 1780606, failures_b: 52, drive_days_b: 1790551 },
    created_at: '2026-10-21T10:00:03Z',
    result: {
      evidence_id: EV_RATES,
      tool: 'stats.compare_rates',
      args: { failures_a: 67, drive_days_a: 1780606, failures_b: 52, drive_days_b: 1790551 },
      source: 'mcp-stats',
      generated_at: '2026-10-21T10:00:03Z',
      data: {
        rate_ratio: 1.2957,
        ci_low: 0.8913,
        ci_high: 1.8971,
        p_value: 0.1758,
        method: 'exact_conditional_binomial',
      },
      truncated: false,
      next_page: null,
    },
  },
};

export const report: Report = {
  question: QUESTION,
  scope: {
    source: 'backblaze',
    models: ['ST12000NM0008'],
    date_from: '2026-01-01',
    date_to: '2026-06-30',
  },
  summary: [
    {
      text: 'ST12000NM0008 had an AFR of 1.37% in 2026Q2 with 67 failures.',
      numbers: [
        { value: 1.3712, unit: 'pct', evidence_id: EV_AFR, field: 'series[1].afr_pct' },
        { value: 67, unit: 'count', evidence_id: EV_AFR, field: 'series[1].failures' },
      ],
      evidence_ids: [EV_AFR],
      passage_ids: [],
      status: 'supported',
    },
    {
      text: 'The 2026Q2 rate is 1.30 times the 2026Q1 rate (p = 0.18).',
      numbers: [
        { value: 1.2957, unit: 'ratio', evidence_id: EV_RATES, field: 'rate_ratio' },
        { value: 0.1758, unit: 'p_value', evidence_id: EV_RATES, field: 'p_value' },
      ],
      evidence_ids: [EV_RATES],
      passage_ids: [],
      status: 'supported',
    },
  ],
  findings: [
    {
      text: 'The cohort logged 52 failures in 2026Q1.',
      numbers: [{ value: 52, unit: 'count', evidence_id: EV_AFR, field: 'series[0].failures' }],
      evidence_ids: [EV_AFR],
      passage_ids: [],
      status: 'supported',
    },
  ],
  hypotheses: [
    {
      statement: 'Media degradation in part of the cohort.',
      support: [],
      confidence: 'medium',
      how_to_confirm: 'Check pending sectors before failure on every failed drive.',
    },
  ],
  recommended_actions: ['Replace drives with non-zero SMART 197.'],
  limitations: ['Many failures show no prior SMART signal.'],
  unverified: [
    {
      text: 'About 41.2% of failures sat in one data center.',
      numbers: [{ value: 41.2, unit: 'pct', evidence_id: EV_AFR, field: 'series[1].failures' }],
      evidence_ids: [EV_AFR],
      passage_ids: [],
      status: 'unsupported',
    },
  ],
  mode: 'single',
  model_id: 'gpt-oss-20b',
  prompt_hashes: { agent: 'sha256:abc' },
};

export const steps: Step[] = [
  {
    seq: 1,
    node: 'agent',
    kind: 'plan',
    payload: {
      plan: {
        restated_question: 'Is the Q2 2026 AFR rise of ST12000NM0008 real?',
        scope: report.scope,
        tasks: [{ id: 't1', kind: 'data', goal: 'Get quarterly AFR', depends_on: [] }],
      },
    },
    started_at: '2026-10-21T10:00:00Z',
    ended_at: '2026-10-21T10:00:01Z',
  },
  {
    seq: 2,
    node: 'agent',
    kind: 'tool_call',
    payload: {
      tool: 'fleet.cohort_afr',
      args: evidence[EV_AFR]!.args,
      evidence_id: EV_AFR,
      ok: true,
      summary: '2 quarters',
    },
    started_at: '2026-10-21T10:00:01Z',
    ended_at: '2026-10-21T10:00:02Z',
  },
  {
    seq: 3,
    node: 'agent',
    kind: 'tool_call',
    payload: {
      tool: 'stats.compare_rates',
      args: evidence[EV_RATES]!.args,
      evidence_id: EV_RATES,
      ok: true,
      summary: 'ratio 1.30',
    },
    started_at: '2026-10-21T10:00:02Z',
    ended_at: '2026-10-21T10:00:03Z',
  },
  {
    seq: 4,
    node: 'agent',
    kind: 'draft',
    payload: { claims: [...report.summary, ...report.findings, ...report.unverified] },
    started_at: '2026-10-21T10:00:03Z',
    ended_at: '2026-10-21T10:00:09Z',
  },
  {
    seq: 5,
    node: 'checker',
    kind: 'check',
    payload: { supported: 3, unsupported: 1, notes: ['One claim cites a count as a percentage.'] },
    started_at: '2026-10-21T10:00:09Z',
    ended_at: '2026-10-21T10:00:10Z',
  },
];

export const detail: InvestigationDetail = {
  id: INVESTIGATION_ID,
  question: QUESTION,
  scope: null,
  mode: 'single',
  status: 'completed',
  llm_model: 'gpt-oss-20b',
  started_at: '2026-10-21T10:00:00Z',
  finished_at: '2026-10-21T10:00:42Z',
  tokens_in: 21345,
  tokens_out: 2048,
  cost_usd: 0,
  report,
  markdown: '# Report',
};

export const cohorts: CohortCompareRow[] = [
  {
    model: 'MODEL-B',
    drive_days: 900000,
    failures: 40,
    afr_pct: 1.62,
    ci_low_pct: 1.16,
    ci_high_pct: 2.21,
    rate_ratio_vs_fleet: 1.25,
  },
  {
    model: 'MODEL-A',
    drive_days: 1200000,
    failures: 90,
    afr_pct: 2.74,
    ci_low_pct: 2.2,
    ci_high_pct: 3.36,
    rate_ratio_vs_fleet: 2.1,
  },
  {
    model: 'MODEL-D',
    drive_days: 300000,
    failures: 3,
    afr_pct: 0.37,
    ci_low_pct: 0.08,
    ci_high_pct: 1.07,
    rate_ratio_vs_fleet: 0.28,
  },
  {
    model: 'MODEL-C',
    drive_days: 700000,
    failures: 18,
    afr_pct: 0.94,
    ci_low_pct: 0.56,
    ci_high_pct: 1.48,
    rate_ratio_vs_fleet: 0.72,
  },
];

export const summary: FleetSummary = {
  source: 'backblaze',
  from: '2026-04-01',
  to: '2026-06-30',
  drives: 41000,
  drive_days: 3100000,
  failures: 151,
  afr_pct: 1.3,
  ci_low_pct: 1.1,
  ci_high_pct: 1.52,
  method: 'exact_poisson_95',
  generated_at: '2026-10-21T10:00:00Z',
};

const afrResponse: CohortAfrResponse = {
  source: 'backblaze',
  model: 'MODEL-A',
  series: [
    {
      period: '2025Q3',
      drive_days: 1100000,
      failures: 50,
      afr_pct: 1.66,
      ci_low_pct: 1.23,
      ci_high_pct: 2.19,
    },
    {
      period: '2025Q4',
      drive_days: 1150000,
      failures: 55,
      afr_pct: 1.75,
      ci_low_pct: 1.31,
      ci_high_pct: 2.27,
    },
    {
      period: '2026Q1',
      drive_days: 1180000,
      failures: 60,
      afr_pct: 1.86,
      ci_low_pct: 1.42,
      ci_high_pct: 2.39,
    },
    {
      period: '2026Q2',
      drive_days: 1200000,
      failures: 90,
      afr_pct: 2.74,
      ci_low_pct: 2.2,
      ci_high_pct: 3.36,
    },
  ],
  method: 'exact_poisson_95',
  generated_at: '2026-10-21T10:00:00Z',
};

const smartResponse: SmartTrendResponse = {
  source: 'backblaze',
  model: 'MODEL-A',
  attr: 197,
  series: afrResponse.series.map((p, i) => ({
    period: p.period,
    p50: 0,
    p95: 3 + i * 2,
    nonzero_share: 0.02 + i * 0.01,
    n_drives: 240,
  })),
};

const failedResponse: FailedDrivesResponse = {
  items: [
    {
      drive_id: 'ZL0ABC123',
      failed_on: '2026-06-28',
      age_days: 1702,
      last_smart: { '5': 8, '187': 0, '197': 24, '198': 16 },
    },
    {
      drive_id: 'ZL0DEF456',
      failed_on: '2026-06-11',
      age_days: 1650,
      last_smart: { '5': 0, '187': 2, '197': 0, '198': 0 },
    },
  ],
  page: 0,
  size: 25,
  total: 2,
};

export const alerts: SuggestedAlert[] = [
  {
    alert_id: '0b7f6c8e-1d2a-4c3b-9e5f-6a7b8c9d0e1f',
    source: 'backblaze',
    model: 'MODEL-A',
    window_start: '2026-04-01',
    window_end: '2026-06-30',
    baseline_afr: 1.86,
    current_afr: 2.74,
    rate_ratio: 1.47,
    p_value: 0.012,
    status: 'open',
    opened_at: '2026-07-01T06:00:00Z',
    suggested_question: 'Why did the failure rate of MODEL-A rise in Q2 2026?',
  },
];

function sse(events: { event: string; data: unknown }[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join('');
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

export interface MockLog {
  posts: unknown[];
}

/** Route every /api/agent and /api/fleet call to the fixtures above. No backend runs in tests. */
export async function mockApi(
  page: Page,
  options: { evals?: unknown; alerts?: SuggestedAlert[] } = {},
): Promise<MockLog> {
  const log: MockLog = { posts: [] };

  await page.route('**/api/agent/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/agent', '');

    if (path === '/v1/investigations' && request.method() === 'POST') {
      log.posts.push(request.postDataJSON());
      return json(route, { id: INVESTIGATION_ID, status: 'queued' }, 202);
    }
    if (path === '/v1/investigations') return json(route, { items: [detail] });
    if (path === `/v1/investigations/${INVESTIGATION_ID}/events`) {
      return route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: sse([
          ...steps.map((s) => ({ event: 'step', data: s })),
          { event: 'report', data: { status: 'completed', report, markdown: detail.markdown } },
        ]),
      });
    }
    if (path === `/v1/investigations/${INVESTIGATION_ID}`) return json(route, detail);
    const ev = /^\/v1\/investigations\/[^/]+\/evidence\/([^/]+)$/.exec(path);
    if (ev) {
      const record = evidence[decodeURIComponent(ev[1] ?? '')];
      return record ? json(route, record) : json(route, { title: 'Not found', status: 404 }, 404);
    }
    if (path === '/v1/alerts/suggested') return json(route, options.alerts ?? alerts);
    if (path === '/v1/evals/latest') {
      return options.evals
        ? json(route, options.evals)
        : json(route, { title: 'No eval run', status: 404 }, 404);
    }
    return json(route, { title: 'Unexpected request in test', status: 404 }, 404);
  });

  await page.route('**/api/fleet/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/fleet', '');
    if (path === '/v1/cohorts/compare') return json(route, { source: 'backblaze', cohorts });
    if (path === '/v1/fleet/summary') return json(route, summary);
    if (path.endsWith('/afr')) return json(route, afrResponse);
    if (path.endsWith('/smart-trend')) return json(route, smartResponse);
    if (path.endsWith('/failed-drives')) return json(route, failedResponse);
    return json(route, { title: 'Unexpected request in test', status: 404 }, 404);
  });

  return log;
}
