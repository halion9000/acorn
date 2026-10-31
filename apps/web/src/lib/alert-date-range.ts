/**
 * The date range on the Alerts page. The page keeps the CHOICE (today, last 7 days, a custom pair of dates) and works out the actual instants each time it asks the server, so a
 * list left open past midnight, or a choice made yesterday, never points at the wrong day. Days are the person's own (their browser's time zone), and the server is sent the
 * start (included) and end (not included) as exact moments.
 */
export type DatePreset = 'all' | 'today' | 'yesterday' | '7d' | '30d' | 'custom';

export interface AlertDateRange {
  preset: DatePreset;
  /** Custom range only: the first day, as YYYY-MM-DD. */
  from?: string;
  /** Custom range only: the last day (included), as YYYY-MM-DD. */
  to?: string;
}

export const DATE_PRESETS: { value: DatePreset; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'custom', label: 'Custom range…' },
];

/** Midnight at the start of a YYYY-MM-DD day in the local time zone, or null when it is not a real date. */
export function parseDay(day: string | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '');
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(y, mo - 1, d);
  return date.getFullYear() === y && date.getMonth() === mo - 1 && date.getDate() === d ? date : null;
}

const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

/** Why a custom range cannot be used, or null. Empty ends are fine (open-ended). */
export function dateRangeError(range: AlertDateRange | undefined): string | null {
  if (!range || range.preset !== 'custom') return null;
  const from = range.from ? parseDay(range.from) : null;
  const to = range.to ? parseDay(range.to) : null;
  if (range.from && !from) return 'The start date is not a valid date.';
  if (range.to && !to) return 'The end date is not a valid date.';
  if (from && to && from > to) return 'The start date is after the end date.';
  return null;
}

/**
 * The moments to send the server (`since` included, `until` not included), or nothing for "all time". "Last 7 days" and "Last 30 days" are whole days counted back from today and
 * including it. A custom range includes both of its days, and either end may be left empty. A range that cannot be used (see dateRangeError) sends nothing, so it never hides alerts.
 */
export function rangeToInstants(range: AlertDateRange | undefined, now: Date = new Date()): { since?: string; until?: string } {
  if (!range || range.preset === 'all' || dateRangeError(range)) return {};
  const today = startOfDay(now);
  switch (range.preset) {
    case 'today':
      return { since: today.toISOString(), until: addDays(today, 1).toISOString() };
    case 'yesterday':
      return { since: addDays(today, -1).toISOString(), until: today.toISOString() };
    case '7d':
      return { since: addDays(today, -6).toISOString() };
    case '30d':
      return { since: addDays(today, -29).toISOString() };
    case 'custom': {
      const from = range.from ? parseDay(range.from) : null;
      const to = range.to ? parseDay(range.to) : null;
      return { ...(from ? { since: from.toISOString() } : {}), ...(to ? { until: addDays(to, 1).toISOString() } : {}) };
    }
    default:
      return {};
  }
}

/** True when the range actually limits the list (so "Clear filters" and the empty-list message know). */
export function isDateLimited(range: AlertDateRange | undefined): boolean {
  if (!range || range.preset === 'all') return false;
  return range.preset !== 'custom' || !!(range.from || range.to);
}
