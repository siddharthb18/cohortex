/**
 * Defensive readers for response shapes the specs leave open (see "UNSPECIFIED" in types.ts).
 * Each accepts a bare array or an object holding the list under one of the given keys.
 */
export function asList<T>(body: unknown, keys: readonly string[] = ['items']): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body !== null && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    for (const key of keys) {
      const value = record[key];
      if (Array.isArray(value)) return value as T[];
    }
  }
  return [];
}
