import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { EvidenceRecord } from '../api/types';
import { compareCited } from '../lib/claimNumbers';
import {
  formatArgValue,
  formatDateTime,
  formatRefValue,
  formatPlain,
  UNIT_LABELS,
} from '../lib/format';
import { resolveEvidenceField } from '../lib/jsonPath';
import { ErrorNotice, SkeletonRows } from './Feedback';
import { AlertIcon, CheckIcon, InfoIcon, XIcon } from './icons';
import { EvidenceContext, type EvidenceTarget } from './evidenceContext';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<EvidenceTarget | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const open = useCallback((target: EvidenceTarget, trigger: HTMLElement | null) => {
    triggerRef.current = trigger;
    setCurrent(target);
  }, []);

  const close = useCallback(() => {
    setCurrent(null);
    const trigger = triggerRef.current;
    triggerRef.current = null;
    // Return focus to the number or link that opened the drawer.
    if (trigger) requestAnimationFrame(() => trigger.focus());
  }, []);

  const value = useMemo(() => ({ current, open, close }), [current, open, close]);

  return (
    <EvidenceContext.Provider value={value}>
      {children}
      {current && <EvidenceDrawer target={current} onClose={close} />}
    </EvidenceContext.Provider>
  );
}

function EvidenceDrawer({ target, onClose }: { target: EvidenceTarget; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const query = useQuery({
    queryKey: ['evidence', target.investigationId, target.evidenceId],
    queryFn: () => api.getEvidence(target.investigationId, target.evidenceId),
    staleTime: Infinity,
  });

  // Modal behaviour: background inert, focus moves in, Escape closes, Tab stays inside.
  useEffect(() => {
    const shell = document.getElementById('app-shell');
    shell?.setAttribute('inert', '');
    closeRef.current?.focus();
    return () => shell?.removeAttribute('inert');
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
  }, [target.key]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !panelRef.current) return;
    const items = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    );
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <>
      <div className="drawer-scrim" onClick={onClose} aria-hidden />
      <div
        ref={panelRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        onKeyDown={onKeyDown}
        data-testid="evidence-drawer"
      >
        <div className="drawer-head">
          <div>
            <h2 id="evidence-title">Evidence</h2>
            <p>{target.evidenceId}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="icon-button"
            aria-label="Close evidence"
            onClick={onClose}
          >
            <XIcon size={18} />
          </button>
        </div>
        <div className="drawer-body">
          {query.isPending ? (
            <SkeletonRows rows={5} />
          ) : query.isError ? (
            <ErrorNotice error={query.error} title="Could not load this evidence." />
          ) : (
            <EvidenceContent record={query.data} target={target} />
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}

function EvidenceContent({ record, target }: { record: EvidenceRecord; target: EvidenceTarget }) {
  const envelope = record.result;
  const ref = target.ref;
  const resolved = ref ? resolveEvidenceField(envelope, ref.field) : null;
  const comparison = ref && resolved?.found ? compareCited(ref, resolved.value) : 'unknown';
  const toolError =
    envelope.data && typeof envelope.data === 'object' && 'error' in envelope.data
      ? (envelope.data as { error?: { code?: string; message?: string } }).error
      : undefined;

  return (
    <>
      {ref && (
        <section className="drawer-section" aria-label="Cited value">
          {target.claimText && <p className="claim-quote">{target.claimText}</p>}
          <div className="value-compare" style={{ marginTop: target.claimText ? 14 : 0 }}>
            <div>
              <div className="value-label">Cited in the report</div>
              <div className="value-big">{formatRefValue(ref)}</div>
              <div className="value-path">{UNIT_LABELS[ref.unit]}</div>
            </div>
            <div>
              <div className="value-label">Value in the evidence</div>
              <div className="value-big" data-testid="evidence-value">
                {resolved?.found ? displayValue(resolved.value) : 'Not found'}
              </div>
              <div className="value-path">data.{ref.field}</div>
            </div>
          </div>
          <div className="match-line">
            {comparison === 'match' ? (
              <span className="badge badge-good">
                <CheckIcon size={12} /> Matches within tolerance
              </span>
            ) : comparison === 'mismatch' ? (
              <span className="badge badge-bad">
                <XIcon size={12} /> Does not match
              </span>
            ) : resolved && !resolved.found ? (
              <span className="badge badge-warn">
                <AlertIcon size={12} /> Field not found: {resolved.reason}
              </span>
            ) : (
              <span className="badge">
                <InfoIcon size={12} /> No tolerance is defined for {UNIT_LABELS[ref.unit]} values
              </span>
            )}
          </div>
        </section>
      )}

      <section className="drawer-section">
        <h3>Tool call</h3>
        <dl className="tool-card">
          <dt>Tool</dt>
          <dd className="mono" data-testid="evidence-tool">
            {record.tool}
          </dd>
          <dt>Source</dt>
          <dd>{envelope.source}</dd>
          <dt>Recorded</dt>
          <dd>{formatDateTime(record.created_at)}</dd>
          {envelope.truncated && (
            <>
              <dt>Truncated</dt>
              <dd>Yes, next page {String(envelope.next_page)}</dd>
            </>
          )}
        </dl>
        {toolError && (
          <div className="notice notice-error" style={{ marginTop: 12 }}>
            <AlertIcon />
            <div>
              <strong>{toolError.code ?? 'error'}</strong> {toolError.message}
            </div>
          </div>
        )}
      </section>

      <section className="drawer-section">
        <h3>Arguments</h3>
        <table className="args-table" data-testid="evidence-args">
          <tbody>
            {Object.entries(record.args).map(([key, value]) => (
              <tr key={key}>
                <th scope="row">{key}</th>
                <td>{formatArgValue(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="drawer-section">
        <details className="json-details">
          <summary>Full result JSON</summary>
          <pre tabIndex={0} aria-label="Full result JSON">
            {JSON.stringify(envelope, null, 2)}
          </pre>
        </details>
      </section>
    </>
  );
}

function displayValue(value: unknown): string {
  if (typeof value === 'number') return formatPlain(value);
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
