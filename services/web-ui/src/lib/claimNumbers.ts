import type { Claim, NumberRef } from '../api/types';

/**
 * Number-to-evidence linking (FR-UI-6).
 *
 * A Claim carries its text and, separately, the NumberRefs it cites. The text has no markers, so
 * we find each cited number in the text: scan numeric tokens left to right and give each NumberRef
 * (in citation order) the first unclaimed token whose value matches. A token matches when it is
 * within half a unit of its last shown digit (so "1.37" matches 1.3712) or within 0.5% relative.
 * NumberRefs we cannot place are returned as `unplaced` so the UI still renders them as links.
 */
export type ClaimSegment =
  | { kind: 'text'; text: string }
  | { kind: 'number'; text: string; ref: NumberRef; refIndex: number };

export interface LinkedClaim {
  segments: ClaimSegment[];
  unplaced: { ref: NumberRef; refIndex: number }[];
}

// Digits not glued to a preceding letter/digit/dot (so model names like ST12000NM000J and labels
// like 2026Q2's "Q2" never match), with optional thousands separators, decimals, exponent and a
// k/M/B suffix.
const NUMBER_TOKEN =
  /(?<![A-Za-z0-9_.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:[eE]([-+]?\d+))?([kKMB](?![A-Za-z]))?/g;

const SUFFIX_SCALE: Record<string, number> = { k: 1e3, K: 1e3, M: 1e6, B: 1e9 };

interface Token {
  start: number;
  end: number;
  text: string;
  value: number;
  halfUnit: number;
}

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  for (const match of text.matchAll(NUMBER_TOKEN)) {
    const [whole, intPart = '', fraction = '', exponent, suffix] = match;
    const start = match.index;
    const scale =
      (suffix ? (SUFFIX_SCALE[suffix] ?? 1) : 1) * (exponent ? 10 ** Number(exponent) : 1);
    const value = Number(intPart.replaceAll(',', '') + fraction) * scale;
    const decimals = fraction ? fraction.length - 1 : 0;
    const halfUnit = 0.5 * 10 ** -decimals * scale;
    // A bare 4-digit year such as "2026" is linked only if a NumberRef equals it exactly.
    tokens.push({ start, end: start + whole.length, text: whole, value, halfUnit });
  }
  return tokens;
}

function tokenMatches(token: Token, value: number): boolean {
  const diff = Math.abs(token.value - value);
  if (diff <= token.halfUnit + 1e-9 * Math.max(1, Math.abs(value))) return true;
  return value !== 0 && diff / Math.abs(value) <= 0.005;
}

export function linkClaimNumbers(claim: Pick<Claim, 'text' | 'numbers'>): LinkedClaim {
  const { text, numbers } = claim;
  const tokens = tokenize(text);
  const claimed = new Map<number, number>(); // token index -> ref index
  const unplaced: LinkedClaim['unplaced'] = [];

  numbers.forEach((ref, refIndex) => {
    const tokenIndex = tokens.findIndex((t, i) => !claimed.has(i) && tokenMatches(t, ref.value));
    if (tokenIndex === -1) unplaced.push({ ref, refIndex });
    else claimed.set(tokenIndex, refIndex);
  });

  const segments: ClaimSegment[] = [];
  let cursor = 0;
  tokens.forEach((token, i) => {
    const refIndex = claimed.get(i);
    if (refIndex === undefined) return;
    const ref = numbers[refIndex];
    if (!ref) return;
    if (token.start > cursor)
      segments.push({ kind: 'text', text: text.slice(cursor, token.start) });
    segments.push({ kind: 'number', text: token.text, ref, refIndex });
    cursor = token.end;
  });
  if (cursor < text.length || segments.length === 0) {
    segments.push({ kind: 'text', text: text.slice(cursor) });
  }
  return { segments, unplaced };
}

export type CitedComparison = 'match' | 'mismatch' | 'unknown';

/**
 * Compare a cited number with the value found in its evidence using the contracts §6 rule:
 * percentages match within 0.5% relative or 0.01 absolute; counts match exactly. Other units have
 * no stated tolerance, so the UI shows both values without a verdict.
 */
export function compareCited(ref: NumberRef, actual: unknown): CitedComparison {
  if (typeof actual !== 'number' || !Number.isFinite(actual)) return 'unknown';
  if (ref.unit === 'pct') {
    const diff = Math.abs(actual - ref.value);
    const rel = actual === 0 ? Infinity : diff / Math.abs(actual);
    return diff <= 0.01 + 1e-12 || rel <= 0.005 ? 'match' : 'mismatch';
  }
  if (ref.unit === 'count') return actual === ref.value ? 'match' : 'mismatch';
  return 'unknown';
}
