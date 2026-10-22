import { IS_DEMO } from '../config';
import type { Api } from './api';
import { liveApi } from './liveApi';

/**
 * The active backend. In demo builds the demo implementation is loaded lazily so the live bundle
 * does not carry it.
 */
let demo: Promise<Api> | null = null;

function demoApi(): Promise<Api> {
  demo ??= import('../demo/demoApi.ts').then((m) => m.demoApi);
  return demo;
}

type AsyncMethods = {
  [K in keyof Api]: Api[K] extends (...args: infer A) => Promise<infer R>
    ? (...args: A) => Promise<R>
    : never;
};

function lazy<K extends keyof AsyncMethods>(key: K): AsyncMethods[K] {
  const fn = (...args: unknown[]) =>
    demoApi().then((impl) => (impl[key] as (...a: unknown[]) => Promise<unknown>)(...args));
  return fn as AsyncMethods[K];
}

function buildDemoProxy(): Api {
  return {
    createInvestigation: lazy('createInvestigation'),
    getInvestigation: lazy('getInvestigation'),
    listInvestigations: lazy('listInvestigations'),
    getEvidence: lazy('getEvidence'),
    openEvents(id, handlers) {
      let close: (() => void) | null = null;
      let cancelled = false;
      void demoApi().then((impl) => {
        if (!cancelled) close = impl.openEvents(id, handlers);
      });
      return () => {
        cancelled = true;
        close?.();
      };
    },
    suggestedAlerts: lazy('suggestedAlerts'),
    latestEval: lazy('latestEval'),
    compareCohorts: lazy('compareCohorts'),
    fleetSummary: lazy('fleetSummary'),
    cohortAfr: lazy('cohortAfr'),
    smartTrend: lazy('smartTrend'),
    failedDrives: lazy('failedDrives'),
  };
}

export const api: Api = IS_DEMO ? buildDemoProxy() : liveApi;
export { ApiError, errorMessage, isNotFound } from './api';
