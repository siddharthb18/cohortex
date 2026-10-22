/** Quarter labels `YYYYQn` (implementation-notes §3) and inclusive date windows (§5). */
export type QuarterLabel = string;

const QUARTER = /^(\d{4})Q([1-4])$/;
const LAST_DAY = ['03-31', '06-30', '09-30', '12-31'] as const;
const FIRST_DAY = ['01-01', '04-01', '07-01', '10-01'] as const;

function parse(q: QuarterLabel): { year: number; quarter: number } {
  const match = QUARTER.exec(q);
  if (!match) throw new Error(`Bad quarter label "${q}"`);
  return { year: Number(match[1]), quarter: Number(match[2]) };
}

function ordinal(q: QuarterLabel): number {
  const { year, quarter } = parse(q);
  return year * 4 + (quarter - 1);
}

function fromOrdinal(n: number): QuarterLabel {
  return `${Math.floor(n / 4)}Q${(n % 4) + 1}`;
}

export function quarterRange(q: QuarterLabel): { from: string; to: string } {
  const { year, quarter } = parse(q);
  return { from: `${year}-${FIRST_DAY[quarter - 1]}`, to: `${year}-${LAST_DAY[quarter - 1]}` };
}

export function quarterOf(isoDate: string): QuarterLabel {
  const year = Number(isoDate.slice(0, 4));
  const month = Number(isoDate.slice(5, 7));
  return `${year}Q${Math.floor((month - 1) / 3) + 1}`;
}

export function listQuarters(first: QuarterLabel, last: QuarterLabel): QuarterLabel[] {
  const out: QuarterLabel[] = [];
  for (let n = ordinal(first); n <= ordinal(last); n += 1) out.push(fromOrdinal(n));
  return out;
}

/** Number of quarters from `first` to `last` inclusive; 0 when `last` precedes `first`. */
export function quarterCount(first: QuarterLabel, last: QuarterLabel): number {
  return Math.max(0, ordinal(last) - ordinal(first) + 1);
}

export function windowDates(first: QuarterLabel, last: QuarterLabel): { from: string; to: string } {
  return { from: quarterRange(first).from, to: quarterRange(last).to };
}

/** FR-API-8: windows longer than 8 quarters are rejected by fleet-api with 400. */
export const MAX_WINDOW_QUARTERS = 8;

export function shiftQuarter(q: QuarterLabel, delta: number): QuarterLabel {
  return fromOrdinal(ordinal(q) + delta);
}
