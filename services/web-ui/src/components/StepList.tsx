import type { Step } from '../api/types';
import { durationBetween, formatArgValue, formatDuration } from '../lib/format';
import type { StreamPhase } from '../lib/investigationStream';
import { useEvidence } from './evidenceContext';
import { AlertIcon, CheckIcon, DocIcon, InfoIcon, ToolIcon, XIcon } from './icons';

const KIND_TITLE: Record<Step['kind'], string> = {
  plan: 'Plan',
  tool_call: 'Tool call',
  draft: 'Draft',
  check: 'Evidence check',
  report: 'Report',
  error: 'Error',
};

function Marker({ step }: { step: Step }) {
  switch (step.kind) {
    case 'tool_call':
      return step.payload.ok ? (
        <span className="step-marker ok" aria-hidden>
          <ToolIcon size={11} />
        </span>
      ) : (
        <span className="step-marker fail" aria-hidden>
          <XIcon size={10} />
        </span>
      );
    case 'check':
      return (
        <span className={`step-marker ${step.payload.unsupported > 0 ? 'info' : 'ok'}`} aria-hidden>
          <CheckIcon size={11} />
        </span>
      );
    case 'error':
      return (
        <span className="step-marker fail" aria-hidden>
          <AlertIcon size={11} />
        </span>
      );
    case 'report':
      return (
        <span className="step-marker ok" aria-hidden>
          <DocIcon size={11} />
        </span>
      );
    default:
      return (
        <span className="step-marker info" aria-hidden>
          <InfoIcon size={11} />
        </span>
      );
  }
}

function StepBody({ step, investigationId }: { step: Step; investigationId: string }) {
  const evidence = useEvidence();
  switch (step.kind) {
    case 'plan':
      return (
        <div className="step-body">
          <p>{step.payload.plan.restated_question}</p>
          <ol>
            {step.payload.plan.tasks.map((task) => (
              <li key={task.id}>
                <span className="task-kind">{task.kind}</span> {task.goal}
              </li>
            ))}
          </ol>
        </div>
      );
    case 'tool_call': {
      const p = step.payload;
      const key = `step:${step.seq}`;
      return (
        <div className="step-body">
          <div className="tool-line">
            <span className="tool-name">{p.tool}</span>
            {p.evidence_id && (
              <button
                type="button"
                className="evidence-link"
                aria-haspopup="dialog"
                aria-expanded={evidence.current?.key === key}
                onClick={(event) =>
                  evidence.open(
                    { investigationId, evidenceId: p.evidence_id, key },
                    event.currentTarget,
                  )
                }
              >
                {p.evidence_id}
                <span className="sr-only">, show evidence</span>
              </button>
            )}
            {p.ok ? (
              <span className="badge badge-good">
                <CheckIcon size={12} /> Returned
              </span>
            ) : (
              <span className="badge badge-bad">
                <XIcon size={12} /> Failed
              </span>
            )}
          </div>
          {Object.keys(p.args).length > 0 && (
            <div className="args" aria-label="Arguments">
              {Object.entries(p.args).map(([k, v]) => (
                <span key={k} className="arg">
                  <b>{k}=</b>
                  {formatArgValue(v)}
                </span>
              ))}
            </div>
          )}
          {p.summary && <p className="step-summary">{p.summary}</p>}
        </div>
      );
    }
    case 'draft':
      return (
        <div className="step-body">
          Drafted {step.payload.claims.length} claim{step.payload.claims.length === 1 ? '' : 's'}{' '}
          with {step.payload.claims.reduce((n, c) => n + c.numbers.length, 0)} cited numbers.
        </div>
      );
    case 'check':
      return (
        <div className="step-body">
          <div className="check-counts">
            <span className="badge badge-good">
              <CheckIcon size={12} /> {step.payload.supported} supported
            </span>
            <span className={`badge ${step.payload.unsupported > 0 ? 'badge-warn' : ''}`}>
              <AlertIcon size={12} /> {step.payload.unsupported} unsupported
            </span>
          </div>
          {step.payload.notes.length > 0 && (
            <ul className="check-notes">
              {step.payload.notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      );
    case 'report':
      return (
        <div className="step-body">Report written ({step.payload.status.replace('_', ' ')}).</div>
      );
    case 'error':
      return <div className="step-body">{step.payload.message}</div>;
  }
}

interface Props {
  steps: Step[];
  phase: StreamPhase;
  investigationId: string;
}

export function StepList({ steps, phase, investigationId }: Props) {
  const live = phase === 'connecting' || phase === 'streaming';
  return (
    <ol className="steps" aria-label="Investigation steps" data-testid="steps">
      {steps.map((step) => (
        <li key={step.seq} className="step" data-kind={step.kind}>
          <Marker step={step} />
          <div>
            <div className="step-head">
              <span className="step-title">{KIND_TITLE[step.kind]}</span>
              <span className="step-node">{step.node}</span>
              <span className="step-time">
                {formatDuration(durationBetween(step.started_at, step.ended_at))}
              </span>
            </div>
            <StepBody step={step} investigationId={investigationId} />
          </div>
        </li>
      ))}
      {live && (
        <li className="step" aria-live="polite">
          <span className="step-marker pending" aria-hidden />
          <div>
            <div className="step-head">
              <span className="step-title secondary">
                {steps.length === 0 ? 'Starting the investigation' : 'Working'}
              </span>
            </div>
          </div>
        </li>
      )}
    </ol>
  );
}
