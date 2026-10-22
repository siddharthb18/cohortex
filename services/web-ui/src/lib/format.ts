import type { NumberRef } from '../api/types';

const intFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const compactFormat = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

export function formatInt(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : intFormat.format(value);
}

export function formatCompact(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : compactFormat.format(value);
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? '–' : `${value.toFixed(digits)}%`;
}

export function formatRatio(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? '–' : `${value.toFixed(digits)}×`;
}

export function formatPValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  if (value === 0) return '0';
  if (value < 0.001) return value.toExponential(1);
  return value.toPrecision(2);
}

export function formatPlain(value: number): string {
  if (Number.isInteger(value)) return intFormat.format(value);
  const abs = Math.abs(value);
  if (abs !== 0 && abs < 0.001) return value.toExponential(2);
  return String(Number(value.toPrecision(6)));
}

/** Format a cited number for display next to its unit. */
export function formatRefValue(ref: Pick<NumberRef, 'value' | 'unit'>): string {
  switch (ref.unit) {
    case 'pct':
      return `${formatPlain(ref.value)}%`;
    case 'count':
    case 'drive_days':
      return formatInt(ref.value);
    case 'days':
      return `${formatInt(ref.value)} days`;
    case 'ratio':
      return `${formatPlain(ref.value)}×`;
    case 'p_value':
      return formatPValue(ref.value);
    case 'raw':
      return formatPlain(ref.value);
  }
}

export const UNIT_LABELS: Record<NumberRef['unit'], string> = {
  pct: 'percent',
  count: 'count',
  drive_days: 'drive-days',
  days: 'days',
  ratio: 'ratio',
  p_value: 'p-value',
  raw: 'raw value',
};

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return '–';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

export function durationBetween(
  start: string | null | undefined,
  end: string | null | undefined,
): number | null {
  if (!start || !end) return null;
  const ms = Date.parse(end) - Date.parse(start);
  return Number.isFinite(ms) ? ms : null;
}

const dateTimeFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '–';
  const t = Date.parse(iso);
  return Number.isFinite(t) ? dateTimeFormat.format(t) : iso;
}

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '–';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const seconds = Math.round((now - t) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDateTime(iso);
}

export function formatArgValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null || value === undefined) return 'null';
  return JSON.stringify(value);
}
