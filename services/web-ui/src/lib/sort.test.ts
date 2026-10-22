import { describe, expect, it } from 'vitest';
import { nextSort, sortRows } from './sort';

const rows = [
  { model: 'B', afr_pct: 1.2, failures: 4 },
  { model: 'A', afr_pct: 2.5, failures: 9 },
  { model: 'C', afr_pct: 1.2, failures: 2 },
  { model: 'D', afr_pct: null as number | null, failures: 0 },
];

describe('sortRows', () => {
  it('sorts numbers descending with ties kept in original order and nulls last', () => {
    expect(sortRows(rows, 'afr_pct', 'desc').map((r) => r.model)).toEqual(['A', 'B', 'C', 'D']);
  });
  it('sorts numbers ascending with nulls still last', () => {
    expect(sortRows(rows, 'afr_pct', 'asc').map((r) => r.model)).toEqual(['B', 'C', 'A', 'D']);
  });
  it('sorts strings', () => {
    expect(sortRows(rows, 'model', 'asc').map((r) => r.model)).toEqual(['A', 'B', 'C', 'D']);
    expect(sortRows(rows, 'model', 'desc').map((r) => r.model)).toEqual(['D', 'C', 'B', 'A']);
  });
  it('does not mutate the input', () => {
    const copy = [...rows];
    sortRows(rows, 'failures', 'asc');
    expect(rows).toEqual(copy);
  });
});

describe('nextSort', () => {
  it('starts numeric columns descending and toggles on repeat', () => {
    expect(nextSort({ key: 'model', dir: 'asc' }, 'afr_pct', 'desc')).toEqual({
      key: 'afr_pct',
      dir: 'desc',
    });
    expect(nextSort({ key: 'afr_pct', dir: 'desc' }, 'afr_pct', 'desc')).toEqual({
      key: 'afr_pct',
      dir: 'asc',
    });
  });
});
