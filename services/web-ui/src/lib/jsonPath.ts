import type { EvidenceEnvelope } from '../api/types';

/**
 * Minimal JSON-path reader for `NumberRef.field` (contracts §6), e.g. `series[0].afr_pct`.
 *
 * Grammar: an optional leading `$` or `$.`, then segments joined by `.`; each segment is a key,
 * an `[n]` index, or a quoted key `["k"]` / `['k']`. No wildcards, filters or slices: a field
 * must name exactly one value.
 */
export type PathSegment = string | number;

export type ResolveResult = { found: true; value: unknown } | { found: false; reason: string };

export function parsePath(path: string): PathSegment[] {
  let rest = path.trim();
  if (rest.startsWith('$')) rest = rest.slice(1);
  if (rest.startsWith('.')) rest = rest.slice(1);
  if (rest === '') throw new Error('Empty path');

  const segments: PathSegment[] = [];
  let i = 0;
  let expectKey = true; // a bare key is allowed at the start and after a dot

  while (i < rest.length) {
    const ch = rest[i];
    if (ch === '[') {
      const close = rest.indexOf(']', i);
      if (close === -1) throw new Error(`Unclosed bracket in "${path}"`);
      const inner = rest.slice(i + 1, close).trim();
      const quoted = /^(["'])(.*)\1$/.exec(inner);
      if (quoted) {
        segments.push(quoted[2] ?? '');
      } else if (/^\d+$/.test(inner)) {
        segments.push(Number(inner));
      } else {
        throw new Error(`Bad index "${inner}" in "${path}"`);
      }
      i = close + 1;
      expectKey = false;
    } else if (ch === '.') {
      if (expectKey) throw new Error(`Empty segment in "${path}"`);
      i += 1;
      expectKey = true;
      if (i >= rest.length) throw new Error(`Trailing dot in "${path}"`);
    } else {
      if (!expectKey) throw new Error(`Expected "." or "[" in "${path}"`);
      const match = /^[^.[\]]+/.exec(rest.slice(i));
      if (!match) throw new Error(`Bad segment in "${path}"`);
      segments.push(match[0]);
      i += match[0].length;
      expectKey = false;
    }
  }
  return segments;
}

function hasOwn(target: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(target, key);
}

export function resolvePath(root: unknown, path: string): ResolveResult {
  let segments: PathSegment[];
  try {
    segments = parsePath(path);
  } catch (err) {
    return { found: false, reason: err instanceof Error ? err.message : 'Bad path' };
  }

  let current: unknown = root;
  for (const segment of segments) {
    if (Array.isArray(current)) {
      const index =
        typeof segment === 'number' ? segment : /^\d+$/.test(segment) ? Number(segment) : NaN;
      if (!Number.isInteger(index) || index < 0 || index >= current.length) {
        return { found: false, reason: `No element ${String(segment)} in "${path}"` };
      }
      current = current[index] as unknown;
    } else if (current !== null && typeof current === 'object') {
      const key = String(segment);
      if (!hasOwn(current, key)) {
        return { found: false, reason: `No key "${key}" in "${path}"` };
      }
      current = (current as Record<string, unknown>)[key];
    } else {
      return { found: false, reason: `Cannot read "${String(segment)}" of a scalar in "${path}"` };
    }
  }
  return { found: true, value: current };
}

/**
 * Resolve a NumberRef field against an evidence envelope. Fields are relative to the envelope's
 * `data`; a field that already starts with `data` is also accepted against the envelope itself.
 */
export function resolveEvidenceField(envelope: EvidenceEnvelope, field: string): ResolveResult {
  const inData = resolvePath(envelope.data, field);
  if (inData.found) return inData;
  if (/^\$?\.?data(\.|\[|$)/.test(field.trim())) {
    const inEnvelope = resolvePath(envelope, field);
    if (inEnvelope.found) return inEnvelope;
  }
  return inData;
}
