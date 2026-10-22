import { describe, expect, it } from 'vitest';
import { compareCited, linkClaimNumbers } from './claimNumbers';
import type { Claim, NumberRef } from '../api/types';

const ref = (value: number, unit: NumberRef['unit'], id = 'ev_a', field = 'x'): NumberRef => ({
  value,
  unit,
  evidence_id: id,
  field,
});
const claim = (text: string, numbers: NumberRef[]): Claim => ({
  text,
  numbers,
  evidence_ids: [],
  passage_ids: [],
  status: 'supported',
});

function linkedTexts(c: Claim): string[] {
  return linkClaimNumbers(c)
    .segments.filter((s) => s.kind === 'number')
    .map((s) => s.text);
}

describe('linkClaimNumbers', () => {
  it('links every cited number to its occurrence in the text', () => {
    const c = claim('ST12000NM000J had an AFR of 1.37% across 98,189 drive-days with 6 failures.', [
      ref(1.3712, 'pct', 'ev_1', 'series[0].afr_pct'),
      ref(98189, 'drive_days', 'ev_1', 'series[0].drive_days'),
      ref(6, 'count', 'ev_1', 'series[0].failures'),
    ]);
    const { segments, unplaced } = linkClaimNumbers(c);
    expect(unplaced).toEqual([]);
    expect(linkedTexts(c)).toEqual(['1.37', '98,189', '6']);
    // Text is preserved exactly when segments are joined back together.
    expect(segments.map((s) => s.text).join('')).toBe(c.text);
  });

  it('does not link digits inside model names or quarter labels', () => {
    const c = claim('In 2026Q2 ST12000NM000J logged 12 failures.', [ref(12, 'count')]);
    expect(linkedTexts(c)).toEqual(['12']);
  });

  it('matches rounded values within half a unit of the last shown digit', () => {
    const c = claim('AFR rose to 2.4% from 1.1%.', [ref(2.4113, 'pct'), ref(1.0952, 'pct')]);
    expect(linkedTexts(c)).toEqual(['2.4', '1.1']);
  });

  it('matches thousand suffixes', () => {
    const c = claim('The cohort logged 98.2k drive-days.', [ref(98189, 'drive_days')]);
    expect(linkedTexts(c)).toEqual(['98.2k']);
  });

  it('links each occurrence once, in citation order', () => {
    const c = claim('3 of 3 drives failed.', [ref(3, 'count', 'ev_a'), ref(3, 'count', 'ev_b')]);
    const numbers = linkClaimNumbers(c).segments.filter((s) => s.kind === 'number');
    expect(numbers.map((s) => (s.kind === 'number' ? s.ref.evidence_id : ''))).toEqual([
      'ev_a',
      'ev_b',
    ]);
  });

  it('returns numbers it cannot place so the UI can still link them', () => {
    const c = claim('The difference is statistically significant (p < 0.001).', [
      ref(0.00042, 'p_value', 'ev_s', 'p_value'),
    ]);
    const { unplaced } = linkClaimNumbers(c);
    expect(unplaced).toHaveLength(1);
    expect(unplaced[0]?.ref.evidence_id).toBe('ev_s');
  });

  it('handles claims without numbers', () => {
    const c = claim('Backblaze data does not capture first-day failures.', []);
    const { segments, unplaced } = linkClaimNumbers(c);
    expect(segments).toEqual([{ kind: 'text', text: c.text }]);
    expect(unplaced).toEqual([]);
  });
});

describe('compareCited (contracts §6 numeric check rule)', () => {
  it('accepts percentages within 0.01 absolute', () => {
    expect(compareCited(ref(1.37, 'pct'), 1.3712)).toBe('match');
  });
  it('accepts percentages within 0.5% relative', () => {
    expect(compareCited(ref(40.1, 'pct'), 40.25)).toBe('match');
  });
  it('rejects percentages outside both tolerances', () => {
    expect(compareCited(ref(1.5, 'pct'), 1.37)).toBe('mismatch');
  });
  it('requires counts to match exactly', () => {
    expect(compareCited(ref(6, 'count'), 6)).toBe('match');
    expect(compareCited(ref(6, 'count'), 7)).toBe('mismatch');
  });
  it('gives no verdict for units without a stated tolerance or non-numeric values', () => {
    expect(compareCited(ref(2.4, 'ratio'), 2.41)).toBe('unknown');
    expect(compareCited(ref(6, 'count'), 'six')).toBe('unknown');
  });
});
