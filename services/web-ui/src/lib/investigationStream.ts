import type {
  ErrorEventData,
  InvestigationStatus,
  Report,
  ReportEventData,
  Step,
} from '../api/types';

/**
 * State of one investigation's SSE stream (implementation-notes §7): `step` events, then a
 * terminal `report` or `error` event. Replays after a reconnect are de-duplicated by `seq`.
 */
export type StreamPhase = 'idle' | 'connecting' | 'streaming' | 'done' | 'failed';

export interface StreamState {
  phase: StreamPhase;
  steps: Step[];
  status: InvestigationStatus | null;
  report: Report | null;
  markdown: string | null;
  error: string | null;
}

export type StreamAction =
  | { type: 'reset' }
  | { type: 'connect' }
  | { type: 'step'; step: Step }
  | { type: 'report'; data: ReportEventData }
  | { type: 'error'; data: ErrorEventData }
  | { type: 'connection_lost'; message: string };

export const initialStreamState: StreamState = {
  phase: 'idle',
  steps: [],
  status: null,
  report: null,
  markdown: null,
  error: null,
};

function upsertStep(steps: Step[], step: Step): Step[] {
  const index = steps.findIndex((s) => s.seq === step.seq);
  if (index >= 0) {
    const next = steps.slice();
    next[index] = step;
    return next;
  }
  return [...steps, step].sort((a, b) => a.seq - b.seq);
}

function isTerminal(phase: StreamPhase): boolean {
  return phase === 'done' || phase === 'failed';
}

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.type) {
    case 'reset':
      return initialStreamState;
    case 'connect':
      return { ...initialStreamState, phase: 'connecting' };
    case 'step':
      return {
        ...state,
        phase: isTerminal(state.phase) ? state.phase : 'streaming',
        status: state.status ?? 'running',
        steps: upsertStep(state.steps, action.step),
      };
    case 'report':
      return {
        ...state,
        phase: 'done',
        status: action.data.status,
        report: action.data.report,
        markdown: action.data.markdown,
        error: null,
      };
    case 'error':
      return {
        ...state,
        phase: 'failed',
        status: action.data.status,
        error: action.data.message,
      };
    case 'connection_lost':
      if (isTerminal(state.phase)) return state;
      return { ...state, phase: 'failed', error: action.message };
  }
}

export interface StepSummary {
  toolCalls: number;
  toolErrors: number;
  supported: number | null;
  unsupported: number | null;
}

export function summarizeSteps(steps: readonly Step[]): StepSummary {
  let toolCalls = 0;
  let toolErrors = 0;
  let supported: number | null = null;
  let unsupported: number | null = null;
  for (const step of steps) {
    if (step.kind === 'tool_call') {
      toolCalls += 1;
      if (!step.payload.ok) toolErrors += 1;
    } else if (step.kind === 'check') {
      supported = step.payload.supported;
      unsupported = step.payload.unsupported;
    }
  }
  return { toolCalls, toolErrors, supported, unsupported };
}

export function parseSseData<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}
