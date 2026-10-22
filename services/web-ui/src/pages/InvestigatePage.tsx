import { useEffect, useId, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorMessage } from '../api';
import type { InvestigationMode, ScopeRequest } from '../api/types';
import { StatusBadge } from '../components/Badges';
import { ErrorNotice } from '../components/Feedback';
import { ReportView } from '../components/ReportView';
import { StepList } from '../components/StepList';
import { AlertIcon, XIcon } from '../components/icons';
import { IS_DEMO } from '../config';
import { useInvestigationStream } from '../hooks/useInvestigationStream';
import { durationBetween, formatDuration, formatInt, formatRelative } from '../lib/format';
import { summarizeSteps } from '../lib/investigationStream';
import { buildPath, navigate, type Route } from '../router';
import { Link } from '../components/Link';

const EXAMPLES = [
  'Which Backblaze drive models had the highest annualized failure rate in Q2 2026 among models with at least 60 drives, and is the top one significantly worse than the fleet?',
  'Is the failure rate of HGST HUH721212ALN604 in Q2 2026 significantly above the fleet average?',
  'How did the AFR of TOSHIBA MG08ACA16TEY change from April to June 2026?',
  'Which Alibaba SSD model had the highest failure rate in 2019?',
];

const DEMO_QUESTION = EXAMPLES[0] ?? '';

/** Read a pre-filled question and scope from the route (Cohort and Alerts pages link here). */
function prefillFromQuery(query: URLSearchParams): {
  question: string;
  scope: ScopeRequest | null;
} {
  const question = query.get('q') ?? (IS_DEMO ? DEMO_QUESTION : '');
  const source = query.get('source');
  const models = query.get('models');
  const from = query.get('from');
  const to = query.get('to');
  const scope: ScopeRequest = {};
  if (source === 'backblaze' || source === 'alibaba') scope.source = source;
  if (models) scope.models = models.split(',').filter(Boolean);
  if (from) scope.from = from;
  if (to) scope.to = to;
  return { question, scope: Object.keys(scope).length > 0 ? scope : null };
}

function scopeLabel(scope: ScopeRequest): string {
  const parts: string[] = [];
  if (scope.source) parts.push(scope.source === 'backblaze' ? 'Backblaze' : 'Alibaba');
  if (scope.models?.length) parts.push(scope.models.join(', '));
  if (scope.from && scope.to) parts.push(`${scope.from} to ${scope.to}`);
  return parts.join(', ');
}

function AskForm({ query }: { query: URLSearchParams }) {
  const initial = prefillFromQuery(query);
  const [question, setQuestion] = useState(initial.question);
  const [scope, setScope] = useState<ScopeRequest | null>(initial.scope);
  const [mode, setMode] = useState<InvestigationMode>('single');
  const queryClient = useQueryClient();
  const questionId = useId();

  const create = useMutation({
    mutationFn: () =>
      api.createInvestigation({
        question: question.trim(),
        mode,
        ...(scope ? { scope } : {}),
      }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ['investigations'] });
      navigate(buildPath(['investigate', created.id]));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (question.trim().length === 0 || create.isPending) return;
    create.mutate();
  };

  return (
    <form className="panel ask-form" onSubmit={submit} aria-label="New investigation">
      <label className="question-label" htmlFor={questionId}>
        Question
      </label>
      <textarea
        id={questionId}
        name="question"
        value={question}
        maxLength={1000}
        placeholder="Ask about a drive cohort's failure rate, a change between quarters, or a SMART signal."
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e);
        }}
      />
      <div className="examples">
        <p className="examples-label" id={`${questionId}-examples`}>
          Try an example
        </p>
        <ul aria-labelledby={`${questionId}-examples`}>
          {EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                className="example"
                title={example}
                onClick={() => setQuestion(example)}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="ask-actions">
        <div className="ask-actions-left">
          <fieldset className="segmented" style={{ border: 'none', margin: 0 }}>
            <legend className="sr-only">Mode</legend>
            {(['single', 'orchestrated'] as const).map((m) => (
              <label key={m}>
                <input
                  type="radio"
                  name="mode"
                  value={m}
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                {m === 'single' ? 'Single agent' : 'Orchestrated'}
              </label>
            ))}
          </fieldset>
          {scope && (
            <span className="scope-chip">
              Scope: {scopeLabel(scope)}
              <button type="button" aria-label="Remove scope" onClick={() => setScope(null)}>
                <XIcon size={12} />
              </button>
            </span>
          )}
        </div>
        <button
          type="submit"
          className="button button-primary"
          disabled={question.trim().length === 0 || create.isPending}
        >
          {create.isPending ? 'Starting…' : 'Run investigation'}
        </button>
      </div>
      {IS_DEMO && (
        <p className="muted" style={{ fontSize: '0.8125rem', marginTop: 12 }}>
          The demo replays one recorded investigation whatever you ask.
        </p>
      )}
      {create.isError && (
        <div style={{ marginTop: 14 }}>
          <ErrorNotice error={create.error} title="Could not start the investigation." />
        </div>
      )}
    </form>
  );
}

function RecentInvestigations({ currentId }: { currentId: string | null }) {
  const recent = useQuery({
    queryKey: ['investigations'],
    queryFn: () => api.listInvestigations(20),
  });

  return (
    <aside className="recent" aria-labelledby="recent-title">
      <h2 id="recent-title">Recent investigations</h2>
      {recent.isPending ? (
        <p className="muted" style={{ fontSize: '0.8125rem' }}>
          Loading…
        </p>
      ) : recent.isError ? (
        <p className="muted" style={{ fontSize: '0.8125rem' }}>
          Could not load the list. {errorMessage(recent.error)}
        </p>
      ) : recent.data.length === 0 ? (
        <p className="muted" style={{ fontSize: '0.8125rem' }}>
          No investigations yet. Ask a question to start one.
        </p>
      ) : (
        <ul>
          {recent.data.map((item) => (
            <li key={item.id}>
              <Link
                to={buildPath(['investigate', item.id])}
                aria-current={item.id === currentId ? 'page' : undefined}
              >
                <span className="recent-q">{item.question}</span>
                <span className="recent-meta">
                  <StatusBadge status={item.status} />
                  <span>{formatRelative(item.started_at)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

function RunView({ id }: { id: string }) {
  const stream = useInvestigationStream(id);
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ['investigation', id],
    queryFn: () => api.getInvestigation(id),
  });

  const finished = stream.phase === 'done' || stream.phase === 'failed';
  useEffect(() => {
    if (!finished) return;
    void queryClient.invalidateQueries({ queryKey: ['investigation', id] });
    void queryClient.invalidateQueries({ queryKey: ['investigations'] });
  }, [finished, id, queryClient]);

  const summary = summarizeSteps(stream.steps);
  const firstPlan = stream.steps.find((s) => s.kind === 'plan');
  const question =
    detail.data?.question ??
    stream.report?.question ??
    (firstPlan?.kind === 'plan' ? firstPlan.payload.plan.restated_question : null);
  // While the stream is live, trust it over the detail record (which may already be final when a
  // stored investigation is replayed).
  const status =
    stream.phase === 'connecting'
      ? 'queued'
      : stream.phase === 'streaming'
        ? 'running'
        : (stream.status ?? detail.data?.status ?? 'queued');
  const report = stream.report ?? (finished ? detail.data?.report : null) ?? null;
  const markdown = stream.markdown ?? detail.data?.markdown ?? null;
  const showTotals = finished && detail.data;
  const latency = showTotals
    ? durationBetween(detail.data.started_at, detail.data.finished_at)
    : null;

  return (
    <div>
      <div className="run-top">
        <Link to="/investigate" className="button button-small">
          New investigation
        </Link>
      </div>
      <header className="run-header">
        {question ? (
          <h1 className="run-question">{question}</h1>
        ) : (
          <span className="skeleton" style={{ width: '70%', height: 22 }} aria-hidden />
        )}
        <dl className="run-meta" aria-label="Run details">
          <div>
            <dt className="sr-only">Status</dt>
            <dd>
              <StatusBadge status={status} />
            </dd>
          </div>
          <div>
            <dt>Mode</dt>
            <dd>
              {(detail.data?.mode ?? report?.mode) === 'orchestrated'
                ? 'Orchestrated'
                : 'Single agent'}
            </dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd className="mono" data-testid="model-id">
              {detail.data?.llm_model ?? report?.model_id ?? '–'}
            </dd>
          </div>
          <div>
            <dt>Tool calls</dt>
            <dd>
              {summary.toolCalls}
              {summary.toolErrors > 0 && (
                <span className="muted"> ({summary.toolErrors} failed)</span>
              )}
            </dd>
          </div>
          {summary.supported !== null && (
            <div>
              <dt>Claims checked</dt>
              <dd>
                {summary.supported} supported, {summary.unsupported} unsupported
              </dd>
            </div>
          )}
          <div>
            <dt>Tokens</dt>
            <dd data-testid="tokens">
              {showTotals && detail.data.tokens_in !== null
                ? `${formatInt(detail.data.tokens_in)} in, ${formatInt(detail.data.tokens_out)} out`
                : '–'}
            </dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd data-testid="latency">{formatDuration(latency)}</dd>
          </div>
        </dl>
      </header>

      <section className="steps-section" aria-labelledby="steps-title">
        <div className="steps-heading">
          <h2 id="steps-title">Steps</h2>
          <p>
            {stream.phase === 'connecting'
              ? 'Connecting to the live stream'
              : stream.phase === 'streaming'
                ? 'Live'
                : `${stream.steps.length} steps`}
          </p>
        </div>
        <StepList steps={stream.steps} phase={stream.phase} investigationId={id} />
      </section>

      {stream.phase === 'failed' && stream.error && (
        <div className="notice notice-error" role="alert" style={{ marginTop: 8 }}>
          <AlertIcon />
          <div>
            <strong>
              {stream.status === 'budget_exceeded'
                ? 'The investigation hit its budget.'
                : stream.status === 'refused'
                  ? 'The agent declined this question.'
                  : 'The investigation stopped.'}
            </strong>{' '}
            {stream.error}
          </div>
        </div>
      )}

      {report && (
        <section aria-label="Report" style={{ marginTop: 20 }}>
          <ReportView report={report} markdown={markdown} investigationId={id} />
        </section>
      )}
      {stream.phase === 'done' && !report && (
        <div className="notice" style={{ marginTop: 8 }}>
          The investigation ended with status {status.replace('_', ' ')} and no report.
        </div>
      )}
    </div>
  );
}

export function InvestigatePage({ route }: { route: Route }) {
  const id = route.segments[0] === 'investigate' ? (route.segments[1] ?? null) : null;

  return (
    <div className="investigate-layout">
      <div>
        {id ? (
          <RunView key={id} id={id} />
        ) : (
          <>
            <div className="ask-intro">
              <h1>Ask why a drive cohort is failing</h1>
              <p>
                Cohortex plans the investigation, calls typed read-only tools over Backblaze and
                Alibaba fleet data, checks every number against the evidence it came from, and
                writes a cited report.
              </p>
            </div>
            {/* Keyed by the query so a new pre-fill (e.g. another alert) resets the form. */}
            <AskForm key={route.query.toString()} query={route.query} />
          </>
        )}
      </div>
      <RecentInvestigations currentId={id} />
    </div>
  );
}
