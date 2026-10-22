import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { EmptyState, ErrorNotice, SkeletonRows } from '../components/Feedback';
import { CheckIcon, XIcon } from '../components/icons';
import { formatDateTime } from '../lib/format';
import {
  formatThreshold,
  METRICS,
  readMetric,
  verdict,
  type MetricDef,
  type MetricValue,
} from '../lib/evals';

function formatValue(def: MetricDef, value: MetricValue): string {
  if (value.kind === 'missing') return 'Not measured';
  if (value.kind === 'latency') {
    const s = (v: number | null) => (v === null ? '–' : `${Math.round(v)} s`);
    return `${s(value.p50)} / ${s(value.p95)}`;
  }
  if (def.format === 'usd') return `$${value.value.toFixed(4)}`;
  return value.value.toFixed(2);
}

function MetricCard({ def, metrics }: { def: MetricDef; metrics: Record<string, unknown> }) {
  const value = readMetric(metrics, def);
  const v = verdict(def, value);
  const target = def.target;
  return (
    <div className="metric" data-testid={`metric-${def.id}`}>
      <div className="metric-head">
        <span>{def.id}</span>
        {v === 'pass' ? (
          <span className="badge badge-good">
            <CheckIcon size={12} /> Meets {def.gate ? 'gate' : 'target'}
          </span>
        ) : v === 'fail' ? (
          <span className="badge badge-bad">
            <XIcon size={12} /> Misses {def.gate ? 'gate' : 'target'}
          </span>
        ) : null}
      </div>
      <h3>{def.name}</h3>
      <div className={`metric-value ${value.kind === 'missing' ? 'missing' : ''}`}>
        {formatValue(def, value)}
      </div>
      <p className="metric-def">{def.definition}</p>
      <div className="metric-thresholds">
        <span>Gate {def.gate ? formatThreshold(def.gate, def.format) : 'none'}</span>
        <span>
          Target{' '}
          {target === null
            ? 'none'
            : 'p50' in target
              ? `≤ ${target.p50} s / ≤ ${target.p95} s`
              : formatThreshold(target, def.format)}
        </span>
      </div>
    </div>
  );
}

export function EvalsPage() {
  const run = useQuery({ queryKey: ['evals', 'latest'], queryFn: () => api.latestEval() });
  const metrics = run.data?.metrics ?? {};

  return (
    <div className="section-gap">
      <div className="page-header">
        <div>
          <h1>Evals</h1>
          <p>
            Latest evaluation run against the golden set. Code graders check numbers against truth
            computed independently from the raw data; thresholds come from the evaluation spec.
          </p>
        </div>
      </div>
      <section className="panel" aria-label="Latest eval run">
        {run.isPending ? (
          <SkeletonRows rows={5} />
        ) : run.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={run.error} title="Could not load eval results." />
          </div>
        ) : !run.data ? (
          <EmptyState title="No eval run published yet">
            Metrics appear here after the first graded run of the golden set. Until then there is
            nothing to report, and nothing is estimated.
          </EmptyState>
        ) : (
          <>
            <div className="panel-pad">
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
                <h2>Run {run.data.id.slice(0, 8)}</h2>
                {run.data.passed ? (
                  <span className="badge badge-good">
                    <CheckIcon size={12} /> Gate passed
                  </span>
                ) : (
                  <span className="badge badge-bad">
                    <XIcon size={12} /> Gate failed
                  </span>
                )}
              </div>
              <div className="eval-meta">
                <span>
                  Started <b>{formatDateTime(run.data.started_at)}</b>
                </span>
                <span>
                  Golden set <b>{run.data.golden_version}</b>
                </span>
                <span>
                  Mode <b>{run.data.mode}</b>
                </span>
                <span>
                  Model <b className="mono">{run.data.llm_model}</b>
                </span>
                <span>
                  Responses <b>{run.data.recorded ? 'recorded' : 'live'}</b>
                </span>
                <span>
                  Commit <b className="mono">{run.data.git_sha.slice(0, 10)}</b>
                </span>
              </div>
            </div>
            <div className="metric-grid">
              {METRICS.map((def) => (
                <MetricCard key={def.id} def={def} metrics={metrics} />
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
