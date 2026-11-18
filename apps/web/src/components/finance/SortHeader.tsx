'use client';

/** A table header cell that sorts its column when pressed (a figure column starts high to low, a name column A to Z; pressing again flips it). */
import { nextSort, sortArrow, type SortState } from '@/lib/tableSort';

export function SortHeader({
  label,
  field,
  sort,
  onSort,
  text = false,
  className = 'px-3 py-2 text-right',
}: {
  label: string;
  field: string;
  sort: SortState | null;
  onSort: (next: SortState) => void;
  text?: boolean;
  className?: string;
}) {
  const active = sort?.key === field;
  return (
    <th className={className} aria-sort={active ? (sort!.desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="uppercase hover:text-gray-200" onClick={() => onSort(nextSort(sort, field, text))}>
        {label}
        {active ? sortArrow(sort, field) : <span className="ml-1 text-gray-600" aria-hidden="true">↕</span>}
      </button>
    </th>
  );
}
