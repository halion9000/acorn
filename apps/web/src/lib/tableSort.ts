/**
 * Sorting for the finance tables (pure). The API sends money as text ("9820.00", "977.12") so it keeps its cents exactly; sorted as text, 977.12 would come after 9820.00. A value that reads as a number
 * is therefore compared as a number, whether it arrives as a number or as text; anything else is compared as text, ignoring case. An empty value (null, undefined, "", or a number that is not finite) sorts last
 * in either direction.
 */

export type SortValue = string | number | null | undefined;

/** The number a value stands for, or null when it is not one ("12.50", " 3 ", 4 are numbers; "Acme", "", "3 h" are not). */
export function asNumber(v: SortValue): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v !== 'string') return null;
  const t = v.trim().replace(/,/g, '');
  if (t === '' || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function isEmpty(v: SortValue): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '') || (typeof v === 'number' && !Number.isFinite(v));
}

/** Compare two values in ascending order (pure). */
export function compareValues(a: SortValue, b: SortValue): number {
  const x = asNumber(a);
  const y = asNumber(b);
  if (x !== null && y !== null) return x - y;
  return String(a ?? '').localeCompare(String(b ?? ''), undefined, { sensitivity: 'base', numeric: true });
}

/** The rows in the order chosen, without changing the original; rows with an empty value come last whichever way it is sorted, and rows that tie keep their order (pure). */
export function sortedBy<T>(rows: readonly T[], value: (row: T) => SortValue, desc: boolean): T[] {
  const dir = desc ? -1 : 1;
  return rows
    .map((row, i) => ({ row, i, v: value(row) }))
    .sort((p, q) => {
      const pe = isEmpty(p.v);
      const qe = isEmpty(q.v);
      if (pe && qe) return p.i - q.i;
      if (pe) return 1;
      if (qe) return -1;
      return compareValues(p.v, q.v) * dir || p.i - q.i;
    })
    .map((p) => p.row);
}

export interface SortState {
  key: string;
  desc: boolean;
}

/** The state after a column header is pressed: the same column flips its direction, a new column starts high-to-low for figures and A-to-Z for names (pure). */
export function nextSort(current: SortState | null, key: string, textColumn = false): SortState {
  if (current?.key === key) return { key, desc: !current.desc };
  return { key, desc: !textColumn };
}

/** The arrow shown next to a header: the direction when it is the sorted column, else nothing (pure). */
export function sortArrow(current: SortState | null, key: string): string {
  return current?.key === key ? (current.desc ? ' ↓' : ' ↑') : '';
}
