import type {
  CohortAfrResponse,
  CohortCompareRow,
  CreateInvestigationRequest,
  CreateInvestigationResponse,
  ErrorEventData,
  EvalRun,
  EvidenceRecord,
  FailedDrivesResponse,
  FleetSummary,
  Granularity,
  InvestigationDetail,
  InvestigationSummary,
  ProblemDetails,
  ReportEventData,
  SmartTrendResponse,
  Source,
  Step,
  SuggestedAlert,
} from './types';

/** Everything the UI needs from the backend; implemented by liveApi and demoApi. */
export interface Api {
  createInvestigation(body: CreateInvestigationRequest): Promise<CreateInvestigationResponse>;
  getInvestigation(id: string): Promise<InvestigationDetail>;
  listInvestigations(limit: number): Promise<InvestigationSummary[]>;
  getEvidence(investigationId: string, evidenceId: string): Promise<EvidenceRecord>;
  /** Subscribe to the SSE stream; returns a function that closes it. */
  openEvents(id: string, handlers: StreamHandlers): () => void;
  suggestedAlerts(): Promise<SuggestedAlert[]>;
  /** Latest eval run, or null when none exists (404). */
  latestEval(mode?: string): Promise<EvalRun | null>;
  compareCohorts(
    params: WindowParams & { minDrives?: number; limit?: number },
  ): Promise<CohortCompareRow[]>;
  fleetSummary(params: WindowParams): Promise<FleetSummary>;
  cohortAfr(params: CohortParams & { granularity: Granularity }): Promise<CohortAfrResponse>;
  smartTrend(
    params: CohortParams & { attr: number; granularity: Granularity },
  ): Promise<SmartTrendResponse>;
  failedDrives(
    params: CohortParams & { page: number; size: number },
  ): Promise<FailedDrivesResponse>;
}

export interface StreamHandlers {
  onStep(step: Step): void;
  onReport(data: ReportEventData): void;
  onError(data: ErrorEventData): void;
  onConnectionLost(message: string): void;
}

export interface WindowParams {
  source: Source;
  from: string;
  to: string;
}

export interface CohortParams extends WindowParams {
  model: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | null;

  constructor(status: number, message: string, problem: ProblemDetails | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
  }
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.problem?.detail ?? error.problem?.title ?? error.message;
  }
  return error instanceof Error ? error.message : 'Unknown error';
}
