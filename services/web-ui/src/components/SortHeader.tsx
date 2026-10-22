import type { SortDir, SortState } from '../lib/sort';
import { SortIcon } from './icons';

interface Props<K extends string> {
  label: string;
  column: K;
  sort: SortState<K>;
  onSort: (column: K) => void;
  numeric?: boolean;
}

/** A sortable column header: a real button inside the th, with aria-sort on the active column. */
export function SortHeader<K extends string>({ label, column, sort, onSort, numeric }: Props<K>) {
  const active = sort.key === column;
  const ariaSort = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined;
  const dir: SortDir | null = active ? sort.dir : null;
  return (
    <th scope="col" className={numeric ? 'num' : undefined} aria-sort={ariaSort}>
      <button type="button" className="sort-button" onClick={() => onSort(column)}>
        {label}
        <SortIcon dir={dir} />
      </button>
    </th>
  );
}
