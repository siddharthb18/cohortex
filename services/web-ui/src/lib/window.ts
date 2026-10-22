import type { Source } from '../api/types';
import { SOURCES } from '../config';
import { listQuarters, MAX_WINDOW_QUARTERS, quarterCount, shiftQuarter } from './quarters';

export interface WindowValue {
  source: Source;
  from: string;
  to: string;
}

/** Clamp a quarter window to the source's coverage and the 8-quarter API limit (FR-API-8). */
export function clampWindow(value: WindowValue): WindowValue {
  const info = SOURCES[value.source];
  const all = listQuarters(info.first, info.last);
  const from = all.includes(value.from) ? value.from : info.defaultFrom;
  let to = all.includes(value.to) ? value.to : info.defaultTo;
  if (quarterCount(from, to) === 0) to = from;
  if (quarterCount(from, to) > MAX_WINDOW_QUARTERS)
    to = shiftQuarter(from, MAX_WINDOW_QUARTERS - 1);
  return { source: value.source, from, to };
}

export function windowFromQuery(
  query: URLSearchParams,
  fallbackSource: Source = 'backblaze',
): WindowValue {
  const s = query.get('source');
  const source: Source = s === 'alibaba' || s === 'backblaze' ? s : fallbackSource;
  const info = SOURCES[source];
  return clampWindow({
    source,
    from: query.get('from') ?? info.defaultFrom,
    to: query.get('to') ?? info.defaultTo,
  });
}
