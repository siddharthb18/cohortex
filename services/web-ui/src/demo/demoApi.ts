import { ApiError, type Api } from '../api/api';
import type {
  CohortCompareRow,
  EvidenceRecord,
  InvestigationDetail,
  InvestigationSummary,
  Step,
  SuggestedAlert,
} from '../api/types';
import * as model from './model.ts';

/**
 * Static demo backend (VITE_DEMO=1): reads canned JSON from public/demo/ and replays the recorded
 * investigation's steps with small delays. All numbers are synthetic.
 */
export interface DemoRecording {
  detail: InvestigationDetail;
  steps: Step[];
  evidence: Record<string, EvidenceRecord>;
}

interface CannedCompare {
  source: model.DemoSource;
  from: string;
  to: string;
  cohorts: CohortCompareRow[];
}

const cache = new Map<string, Promise<unknown>>();

function load<T>(name: string): Promise<T> {
  let promise = cache.get(name);
  if (!promise) {
    promise = fetch(`${import.meta.env.BASE_URL}demo/${name}`).then((r) => {
      if (!r.ok) throw new ApiError(r.status, `Demo file ${name} is missing`);
      return r.json() as Promise<unknown>;
    });
    promise.catch(() => cache.delete(name));
    cache.set(name, promise);
  }
  return promise as Promise<T>;
}

const recording = () => load<DemoRecording>('investigation.json');
const fleetData = () => load<model.DemoFleetData>('fleet-data.json');

async function findModel(source: model.DemoSource, name: string): Promise<model.DemoModel> {
  const data = await fleetData();
  const found = data.sources[source].find((m) => m.model === name);
  if (!found) throw new ApiError(404, `No cohort ${name} in the demo data`);
  return found;
}

/** Delay before each replayed step, by kind (ms). The first step lands well under NFR-UX-1's 3 s. */
const STEP_DELAY: Record<Step['kind'], number> = {
  plan: 500,
  tool_call: 650,
  draft: 1100,
  check: 700,
  report: 350,
  error: 300,
};

export const demoApi: Api = {
  async createInvestigation() {
    const rec = await recording();
    return { id: rec.detail.id, status: 'queued' };
  },

  async getInvestigation(id) {
    const rec = await recording();
    if (id !== rec.detail.id)
      throw new ApiError(404, 'The demo only holds one recorded investigation');
    return rec.detail;
  },

  async listInvestigations(limit) {
    const list = await load<InvestigationSummary[]>('investigations.json');
    return list.slice(0, limit);
  },

  async getEvidence(investigationId, evidenceId) {
    const rec = await recording();
    const evidence = investigationId === rec.detail.id ? rec.evidence[evidenceId] : undefined;
    if (!evidence) throw new ApiError(404, `No evidence ${evidenceId}`);
    return evidence;
  },

  openEvents(id, handlers) {
    const timers: ReturnType<typeof setTimeout>[] = [];
    let cancelled = false;
    recording()
      .then((rec) => {
        if (cancelled) return;
        if (id !== rec.detail.id) {
          handlers.onError({
            status: 'failed',
            message: 'The demo only holds one recorded investigation',
          });
          return;
        }
        let at = 0;
        for (const step of rec.steps) {
          at += STEP_DELAY[step.kind];
          timers.push(setTimeout(() => handlers.onStep(step), at));
        }
        timers.push(
          setTimeout(
            () =>
              handlers.onReport({
                status: rec.detail.status,
                report: rec.detail.report,
                markdown: rec.detail.markdown,
              }),
            at + 300,
          ),
        );
      })
      .catch(() => {
        if (!cancelled) handlers.onConnectionLost('Could not load the recorded investigation.');
      });
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  },

  async suggestedAlerts() {
    return load<SuggestedAlert[]>('alerts.json');
  },

  latestEval() {
    // No eval run is published with the demo: the page shows its empty state.
    return Promise.resolve(null);
  },

  async compareCohorts({ source, from, to, minDrives = 60, limit = 20 }) {
    const canned = await load<CannedCompare[]>('fleet-compare.json');
    const hit = canned.find((c) => c.source === source && c.from === from && c.to === to);
    if (hit && minDrives === 60) return hit.cohorts.slice(0, limit);
    return model.compareCohorts(await fleetData(), source, from, to, minDrives, limit);
  },

  async fleetSummary({ source, from, to }) {
    return model.fleetSummary(await fleetData(), source, from, to);
  },

  async cohortAfr({ source, model: name, from, to, granularity }) {
    const data = await fleetData();
    const m = await findModel(source, name);
    return {
      source,
      model: name,
      series: model.afrSeries(m, from, to, granularity),
      method: 'exact_poisson_95',
      generated_at: data.generated_at,
    };
  },

  async smartTrend({ source, model: name, attr, from, to, granularity }) {
    const data = await fleetData();
    const m = await findModel(source, name);
    return {
      source,
      model: name,
      attr,
      series: model.smartTrend(m, attr, from, to, granularity),
      generated_at: data.generated_at,
    };
  },

  async failedDrives({ source, model: name, from, to, page, size }) {
    const m = await findModel(source, name);
    const all = model.failedDrives(m, source, from, to);
    return { items: all.slice(page * size, page * size + size), page, size, total: all.length };
  },
};
