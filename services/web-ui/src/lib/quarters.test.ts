import { describe, expect, it } from 'vitest';
import { listQuarters, quarterCount, quarterOf, quarterRange, windowDates } from './quarters';

describe('quarters', () => {
  it('maps a quarter label to inclusive dates', () => {
    expect(quarterRange('2026Q2')).toEqual({ from: '2026-04-01', to: '2026-06-30' });
    expect(quarterRange('2024Q1')).toEqual({ from: '2024-01-01', to: '2024-03-31' });
    expect(quarterRange('2019Q4')).toEqual({ from: '2019-10-01', to: '2019-12-31' });
  });
  it('maps a date to its quarter', () => {
    expect(quarterOf('2026-06-30')).toBe('2026Q2');
    expect(quarterOf('2026-07-01')).toBe('2026Q3');
  });
  it('lists quarters inclusively', () => {
    expect(listQuarters('2025Q3', '2026Q2')).toEqual(['2025Q3', '2025Q4', '2026Q1', '2026Q2']);
  });
  it('counts quarters in a window the way fleet-api does (implementation-notes §5)', () => {
    expect(quarterCount('2024Q3', '2026Q2')).toBe(8);
    expect(quarterCount('2024Q2', '2026Q2')).toBe(9);
    expect(quarterCount('2026Q2', '2026Q1')).toBe(0);
  });
  it('builds a date window from two quarters', () => {
    expect(windowDates('2026Q1', '2026Q2')).toEqual({ from: '2026-01-01', to: '2026-06-30' });
  });
});
