import type { Confidence, InvestigationStatus } from '../api/types';
import { AlertIcon, CheckIcon, InfoIcon, XIcon } from './icons';

const STATUS: Record<
  InvestigationStatus,
  { label: string; tone: string; icon: 'ok' | 'bad' | 'warn' | 'info' }
> = {
  queued: { label: 'Queued', tone: '', icon: 'info' },
  running: { label: 'Running', tone: 'badge-accent', icon: 'info' },
  completed: { label: 'Completed', tone: 'badge-good', icon: 'ok' },
  failed: { label: 'Failed', tone: 'badge-bad', icon: 'bad' },
  budget_exceeded: { label: 'Budget exceeded', tone: 'badge-warn', icon: 'warn' },
  refused: { label: 'Refused', tone: '', icon: 'info' },
};

export function StatusBadge({ status }: { status: InvestigationStatus }) {
  const s = STATUS[status] ?? { label: String(status), tone: '', icon: 'info' as const };
  return (
    <span className={`badge ${s.tone}`} data-testid="status-badge">
      {s.icon === 'ok' ? (
        <CheckIcon size={12} />
      ) : s.icon === 'bad' ? (
        <XIcon size={12} />
      ) : s.icon === 'warn' ? (
        <AlertIcon size={12} />
      ) : (
        <InfoIcon size={12} />
      )}
      {s.label}
    </span>
  );
}

const LEVELS: Record<Confidence, number> = { low: 1, medium: 2, high: 3 };

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const level = LEVELS[confidence] ?? 0;
  const label = confidence.charAt(0).toUpperCase() + confidence.slice(1);
  return (
    <span className="confidence" title={`${label} confidence`}>
      <span className="confidence-bars" aria-hidden>
        {[1, 2, 3].map((i) => (
          <i key={i} className={i <= level ? 'on' : undefined} />
        ))}
      </span>
      {label} confidence
    </span>
  );
}
