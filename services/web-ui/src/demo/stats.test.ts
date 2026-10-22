import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { afrCi, compareRates } from './stats';

interface Case {
  failures: number;
  drive_days: number;
  confidence: number;
  afr_pct: number;
  ci_low_pct: number;
  ci_high_pct: number;
}

// The cross-language fixture shared by fleet-api and mcp-stats (implementation-notes §4).
const fixturePath = fileURLToPath(
  new URL('../../../../contracts/fixtures/afr_ci_cases.json', import.meta.url),
);
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as { cases: Case[] };

function close(actual: number, expected: number, rel: number): boolean {
  return Math.abs(actual - expected) <= rel * Math.max(1e-12, Math.abs(expected));
}

describe('demo afrCi', () => {
  it('agrees with the exact Poisson fixture to 1e-6 relative on all cases', () => {
    const bad = fixture.cases.filter((c) => {
      const r = afrCi(c.failures, c.drive_days, c.confidence);
      return (
        !close(r.afr_pct, c.afr_pct, 1e-9) ||
        !close(r.ci_low_pct, c.ci_low_pct, 1e-6) ||
        !close(r.ci_high_pct, c.ci_high_pct, 1e-6)
      );
    });
    expect(fixture.cases.length).toBeGreaterThan(100);
    expect(bad).toEqual([]);
  });
});

describe('demo compareRates', () => {
  it('returns a ratio of rates and a small p-value for a clear increase', () => {
    const r = compareRates(140, 1_800_000, 84, 1_790_000);
    expect(r.rate_ratio).toBeCloseTo(140 / 1_800_000 / (84 / 1_790_000), 9);
    expect(r.p_value).toBeLessThan(0.001);
    expect(r.ci_low).toBeLessThan(r.rate_ratio);
    expect(r.ci_high).toBeGreaterThan(r.rate_ratio);
  });
  it('returns p = 1 for identical rates', () => {
    expect(compareRates(10, 1000, 10, 1000).p_value).toBeCloseTo(1, 9);
  });
});
