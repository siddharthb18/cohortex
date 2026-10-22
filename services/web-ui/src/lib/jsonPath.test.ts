import { describe, expect, it } from 'vitest';
import { parsePath, resolveEvidenceField, resolvePath } from './jsonPath';
import type { EvidenceEnvelope } from '../api/types';

const data = {
  series: [
    { period: '2026Q1', afr_pct: 1.21, failures: 4 },
    { period: '2026Q2', afr_pct: 1.37, failures: 6 },
  ],
  last_smart: { '187': 3, '5': 0 },
  'odd key': { value: 7 },
  rate_ratio: 2.41,
};

describe('parsePath', () => {
  it('splits dotted keys and indices', () => {
    expect(parsePath('series[1].afr_pct')).toEqual(['series', 1, 'afr_pct']);
  });
  it('accepts a leading $ and quoted keys', () => {
    expect(parsePath('$.odd["odd key"].value')).toEqual(['odd', 'odd key', 'value']);
    expect(parsePath("$['a.b'][0]")).toEqual(['a.b', 0]);
  });
  it('rejects malformed paths', () => {
    expect(() => parsePath('series[x]')).toThrow();
    expect(() => parsePath('series[0')).toThrow();
    expect(() => parsePath('a..b')).toThrow();
    expect(() => parsePath('')).toThrow();
  });
});

describe('resolvePath (NumberRef.field)', () => {
  it('reads a field inside an array element', () => {
    expect(resolvePath(data, 'series[1].afr_pct')).toEqual({ found: true, value: 1.37 });
  });
  it('reads a top-level scalar', () => {
    expect(resolvePath(data, 'rate_ratio')).toEqual({ found: true, value: 2.41 });
  });
  it('reads numeric object keys with dot syntax', () => {
    expect(resolvePath(data, 'last_smart.187')).toEqual({ found: true, value: 3 });
  });
  it('reads quoted keys', () => {
    expect(resolvePath(data, '["odd key"].value')).toEqual({ found: true, value: 7 });
  });
  it('indexes into a root array', () => {
    expect(resolvePath([{ a: 1 }, { a: 2 }], '[1].a')).toEqual({ found: true, value: 2 });
  });
  it('reports a missing key without throwing', () => {
    const result = resolvePath(data, 'series[5].afr_pct');
    expect(result.found).toBe(false);
  });
  it('reports a malformed path without throwing', () => {
    expect(resolvePath(data, 'series[').found).toBe(false);
  });
  it('does not walk into prototype properties', () => {
    expect(resolvePath(data, 'series.length').found).toBe(false);
    expect(resolvePath({}, 'constructor').found).toBe(false);
  });
});

describe('resolveEvidenceField', () => {
  const envelope: EvidenceEnvelope = {
    evidence_id: 'ev_1',
    tool: 'fleet.cohort_afr',
    args: {},
    source: 'fleet-api',
    generated_at: '2026-10-02T16:20:11Z',
    data,
    truncated: false,
    next_page: null,
  };
  it('resolves relative to the envelope data', () => {
    expect(resolveEvidenceField(envelope, 'series[0].afr_pct')).toEqual({
      found: true,
      value: 1.21,
    });
  });
  it('falls back to the envelope when the path starts with data.', () => {
    expect(resolveEvidenceField(envelope, 'data.rate_ratio')).toEqual({ found: true, value: 2.41 });
  });
});
