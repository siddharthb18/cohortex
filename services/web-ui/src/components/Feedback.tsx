import type { ReactNode } from 'react';
import { errorMessage } from '../api';
import { AlertIcon } from './icons';

export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  return (
    <div className="notice notice-error" role="alert">
      <AlertIcon />
      <div>
        <strong>{title ?? 'Could not load this data.'}</strong> {errorMessage(error)}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="panel-pad" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <span
          key={i}
          className="skeleton"
          style={{ width: `${90 - i * 12}%`, marginTop: i === 0 ? 0 : 14 }}
        />
      ))}
    </div>
  );
}
