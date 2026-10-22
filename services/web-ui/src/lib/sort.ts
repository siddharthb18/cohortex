export type SortDir = 'asc' | 'desc';

export interface SortState<K extends string = string> {
  key: K;
  dir: SortDir;
}

function isMissing(value: unknown): boolean {
  return (
    value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))
  );
}

/** Stable sort by one column; missing values always sort last. Returns a new array. */
export function sortRows<T, K extends keyof T & string>(
  rows: readonly T[],
  key: K,
  dir: SortDir,
): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const va = a.row[key];
      const vb = b.row[key];
      const ma = isMissing(va);
      const mb = isMissing(vb);
      if (ma || mb) return ma === mb ? a.index - b.index : ma ? 1 : -1;
      let cmp: number;
      if (typeof va === 'number' && typeof vb === 'number') cmp = va - vb;
      else cmp = String(va).localeCompare(String(vb), 'en', { numeric: true });
      return cmp !== 0 ? cmp * sign : a.index - b.index;
    })
    .map(({ row }) => row);
}

/** Clicking a new column starts at its default direction; clicking the same column toggles. */
export function nextSort<K extends string>(
  current: SortState<K>,
  key: K,
  defaultDir: SortDir,
): SortState<K> {
  if (current.key !== key) return { key, dir: defaultDir };
  return { key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
}
