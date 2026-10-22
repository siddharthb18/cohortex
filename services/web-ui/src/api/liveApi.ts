import { AGENT_API, FLEET_API } from '../config';
import { parseSseData } from '../lib/investigationStream';
import { ApiError, type Api, type StreamHandlers } from './api';
import { asList } from './normalize';
import type {
  CohortAfrResponse,
  CohortCompareRow,
  CreateInvestigationResponse,
  ErrorEventData,
  EvalRun,
  EvidenceRecord,
  FailedDrivesResponse,
  FleetSummary,
  InvestigationDetail,
  InvestigationSummary,
  ProblemDetails,
  ReportEventData,
  SmartTrendResponse,
  Step,
  SuggestedAlert,
} from './types';

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check that the backend is running.');
  }
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as ProblemDetails | null;
    throw new ApiError(
      response.status,
      `${response.status} ${response.statusText}`.trim(),
      problem,
    );
  }
  return (await response.json()) as T;
}

const seg = encodeURIComponent;

export const liveApi: Api = {
  createInvestigation(body) {
    return request<CreateInvestigationResponse>(`${AGENT_API}/v1/investigations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  getInvestigation(id) {
    return request<InvestigationDetail>(`${AGENT_API}/v1/investigations/${seg(id)}`);
  },

  async listInvestigations(limit) {
    const body = await request<unknown>(`${AGENT_API}/v1/investigations${query({ limit })}`);
    return asList<InvestigationSummary>(body, ['items', 'investigations']);
  },

  getEvidence(investigationId, evidenceId) {
    return request<EvidenceRecord>(
      `${AGENT_API}/v1/investigations/${seg(investigationId)}/evidence/${seg(evidenceId)}`,
    );
  },

  openEvents(id, handlers: StreamHandlers) {
    const source = new EventSource(`${AGENT_API}/v1/investigations/${seg(id)}/events`);
    let closed = false;
    const close = () => {
      closed = true;
      source.close();
    };

    source.addEventListener('step', (event: MessageEvent<string>) => {
      const step = parseSseData<Step>(event.data);
      if (step) handlers.onStep(step);
    });
    source.addEventListener('report', (event: MessageEvent<string>) => {
      const data = parseSseData<ReportEventData>(event.data);
      close();
      if (data) handlers.onReport(data);
      else handlers.onConnectionLost('The server sent a report the UI could not read.');
    });
    // The server's terminal `event: error` and the browser's connection error share a name.
    // Server events carry `data`; connection errors do not.
    source.addEventListener('error', (event: Event) => {
      if (closed) return;
      if (event instanceof MessageEvent && typeof event.data === 'string' && event.data) {
        const data = parseSseData<ErrorEventData>(event.data);
        close();
        handlers.onError(data ?? { status: 'failed', message: event.data });
        return;
      }
      // EventSource reconnects on its own (readyState CONNECTING); the server replays stored
      // steps, which the reducer de-duplicates. Only a CLOSED source is final.
      if (source.readyState === EventSource.CLOSED) {
        close();
        handlers.onConnectionLost('Lost the connection to the investigation stream.');
      }
    });

    return close;
  },

  async suggestedAlerts() {
    const body = await request<unknown>(`${AGENT_API}/v1/alerts/suggested`);
    return asList<SuggestedAlert>(body, ['items', 'alerts']);
  },

  async latestEval(mode) {
    try {
      return await request<EvalRun>(`${AGENT_API}/v1/evals/latest${query({ mode })}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },

  async compareCohorts({ source, from, to, minDrives, limit }) {
    const body = await request<unknown>(
      `${FLEET_API}/v1/cohorts/compare${query({ source, from, to, min_drives: minDrives, limit })}`,
    );
    return asList<CohortCompareRow>(body, ['cohorts', 'items', 'rows']);
  },

  fleetSummary({ source, from, to }) {
    return request<FleetSummary>(`${FLEET_API}/v1/fleet/summary${query({ source, from, to })}`);
  },

  cohortAfr({ source, model, from, to, granularity }) {
    return request<CohortAfrResponse>(
      `${FLEET_API}/v1/cohorts/${seg(source)}/${seg(model)}/afr${query({ from, to, granularity })}`,
    );
  },

  smartTrend({ source, model, attr, from, to, granularity }) {
    return request<SmartTrendResponse>(
      `${FLEET_API}/v1/cohorts/${seg(source)}/${seg(model)}/smart-trend${query({ attr, from, to, granularity })}`,
    );
  },

  failedDrives({ source, model, from, to, page, size }) {
    return request<FailedDrivesResponse>(
      `${FLEET_API}/v1/cohorts/${seg(source)}/${seg(model)}/failed-drives${query({ from, to, page, size })}`,
    );
  },
};
