'use client';

/**
 * Metrics > Weekly Tech Comparison: one week, each engineer under their pod: days worked, tickets new, opened and closed in the week, older tickets closed, closed in all, net (closed less new), new and closed per day worked,
 * and the Dialpad call tickets left out of those counts; and a line for all pods. Days worked is Monday to Friday less full days off and holidays (Rippling).
 */
import { useCallback, useState } from 'react';

import { NothingYet, Page, selectClass, useMetric } from './kit';
import { RefreshMetrics } from './RefreshMetrics';

interface Line {
  days_worked: number;
  new: number;
  opened_closed: number;
  older_closed: number;
  closed: number;
  net: number;
  new_per_day: number | null;
  closed_per_day: number | null;
  calls_excluded: number;
}
interface Report {
  received_at: string | null;
  weeks: string[];
  week: string | null;
  has_detail: boolean;
  rows: (Line & { pod: string; engineer: string })[];
  total: Line;
}

/** A net of closed less new the way the sheet writes it: negative numbers in parentheses (pure). */
export const netText = (n: number): string => (n < 0 ? `(${Math.abs(n)})` : String(n));
type Row = Line & { pod: string; engineer: string };
export type SortKey = 'pod' | 'engineer' | keyof Line;
const KEYS: SortKey[] = ['days_worked', 'new', 'opened_closed', 'older_closed', 'closed', 'net', 'new_per_day', 'closed_per_day', 'calls_excluded'];

/** The rows ordered by one column (pure); text ascending first, numbers largest first; equal values keep the order given, and a missing per-day rate sorts last. */
export function sortRows(rows: Row[], key: SortKey | null, dir: 1 | -1): Row[] {
  if (key === null) return rows;
  const text = key === 'pod' || key === 'engineer';
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const x = a.r[key];
      const y = b.r[key];
      if (x === null || y === null) return x === y ? a.i - b.i : x === null ? 1 : -1;
      const c = text ? String(x).localeCompare(String(y)) : Number(x) - Number(y);
      return c * dir || a.i - b.i;
    })
    .map((x) => x.r);
}

/** The totals line for the rows shown (pure): sums, with the per-day rates worked out from them. */
export function totalOf(rows: Row[]): Line {
  const sum = (k: 'days_worked' | 'new' | 'opened_closed' | 'older_closed' | 'closed' | 'calls_excluded'): number => rows.reduce((a, r) => a + r[k], 0);
  const days = Math.round(sum('days_worked') * 10) / 10;
  const created = sum('new');
  const closed = sum('closed');
  return { days_worked: days, new: created, opened_closed: sum('opened_closed'), older_closed: sum('older_closed'), closed, net: closed - created, new_per_day: days > 0 ? Math.round((created / days) * 10) / 10 : null, closed_per_day: days > 0 ? Math.round((closed / days) * 10) / 10 : null, calls_excluded: sum('calls_excluded') };
}

/** What the pod filter button says (pure): all pods, the one chosen, or how many. */
export function podSummary(chosen: ReadonlySet<string>, total: number): string {
  if (chosen.size === 0 || chosen.size >= total) return 'Pods: all';
  return chosen.size === 1 ? `Pods: ${[...chosen][0]}` : `Pods: ${chosen.size} of ${total}`;
}
const rate = (n: number | null): string => (n === null ? '–' : n.toFixed(1));
const COLS: [string, (l: Line) => string, boolean][] = [
  ['Days worked', (l) => String(l.days_worked), true],
  ['New this week', (l) => String(l.new), true],
  ['Opened & closed this week', (l) => String(l.opened_closed), true],
  ['Older tickets closed this week', (l) => String(l.older_closed), true],
  ['Closed this week', (l) => String(l.closed), false],
  ['Net (closed - new)', (l) => netText(l.net), false],
  ['New per day worked', (l) => rate(l.new_per_day), false],
  ['Closed per day worked', (l) => rate(l.closed_per_day), false],
  ['Dialpad calls excluded', (l) => String(l.calls_excluded), true],
];

export function WeeklyComparisonView() {
  const [week, setWeek] = useState('');
  const [pods, setPods] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<{ key: SortKey | null; dir: 1 | -1 }>({ key: null, dir: 1 });
  const [reloads, setReloads] = useState(0);
  const reload = useCallback(() => setReloads((n) => n + 1), []);
  const { data, denied, problem } = useMetric<Report>(`/api/v1/reports/metrics/weekly-comparison?${week ? `week=${week}&` : ''}r=${reloads}`);
  const allPods = [...new Set((data?.rows ?? []).map((r) => r.pod))];
  const filtering = pods.size > 0;
  const shown = sortRows(filtering ? (data?.rows ?? []).filter((r) => pods.has(r.pod)) : (data?.rows ?? []), sort.key, sort.dir);
  const total = filtering ? totalOf(shown) : data?.total;
  const press = (key: SortKey): void => setSort((s) => (s.key !== key ? { key, dir: key === 'pod' || key === 'engineer' ? 1 : -1 } : s.dir === (key === 'pod' || key === 'engineer' ? 1 : -1) ? { key, dir: s.dir === 1 ? -1 : 1 } : { key: null, dir: 1 }));
  const mark = (key: SortKey): string => (sort.key === key ? (sort.dir === 1 ? ' ▲' : ' ▼') : '');
  const toggle = (pod: string): void => {
    const next = new Set(pods);
    if (next.has(pod)) next.delete(pod);
    else next.add(pod);
    setPods(next);
  };
  return (
    <Page
      title="Weekly Tech Comparison"
      subtitle="Tickets per engineer for one week, Dialpad call tickets left out. Days worked is Monday to Friday less full days off and holidays."
      denied={denied}
      problem={problem}
      loading={data === null && !denied && !problem}
      empty={<NothingYet show={data?.received_at === null} what="the weekly ticket counts" />}
    >
      {data?.received_at && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-300">
            Week of
            <select aria-label="Week" className={selectClass} value={data.week ?? ''} onChange={(e) => setWeek(e.target.value)}>
              {[...data.weeks].reverse().map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </label>
          <RefreshMetrics receivedAt={data.received_at} reload={reload} />
          </div>
          <details className="relative inline-block text-sm text-gray-300" data-testid="pod-filter">
            <summary className="cursor-pointer select-none rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-gray-100 hover:bg-gray-800">{podSummary(pods, allPods.length)}</summary>
            <div role="group" aria-label="Pods" className="absolute left-0 z-20 mt-1 max-h-72 w-60 overflow-y-auto rounded-lg border border-gray-700 bg-gray-950 p-2 shadow-xl">
              {allPods.map((pod) => (
                <label key={pod} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-gray-800">
                  <input type="checkbox" checked={pods.has(pod)} onChange={() => toggle(pod)} />
                  {pod}
                </label>
              ))}
              {filtering && (
                <button type="button" className="mt-1 w-full rounded px-2 py-1 text-left text-xs text-blue-300 hover:bg-gray-800" onClick={() => setPods(new Set())}>
                  Show all pods
                </button>
              )}
            </div>
          </details>
          {!data.has_detail && (
            <p className="text-sm text-amber-300" role="status">
              CORE has not sent the weekly ticket counts for this week yet; they arrive with its next daily round.
            </p>
          )}
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm" data-testid="weekly-comparison">
              <thead style={{ background: '#1f4e79' }} className="text-xs font-semibold text-white">
                <tr>
                  {([['pod', 'Pod'], ['engineer', 'Tech']] as [SortKey, string][]).map(([key, label]) => (
                    <th key={key} scope="col" className="px-3 py-2 text-left" aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                      <button type="button" onClick={() => press(key)} aria-label={`Sort by ${label}`}>
                        {label}
                        {mark(key)}
                      </button>
                    </th>
                  ))}
                  {COLS.map(([label], i) => (
                    <th key={label} scope="col" className="px-3 py-2 text-center" aria-sort={sort.key === KEYS[i] ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                      <button type="button" onClick={() => press(KEYS[i]!)} aria-label={`Sort by ${label}`}>
                        {label}
                        {mark(KEYS[i]!)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {shown.map((r, i) => (
                  <tr key={`${r.pod}|${r.engineer}`} className={i % 2 ? 'bg-gray-900/40' : ''}>
                    <td className="px-3 py-1.5">{r.pod}</td>
                    <td className="px-3 py-1.5">{r.engineer}</td>
                    {COLS.map(([label, text, input]) => (
                      <td key={label} className={`px-3 py-1.5 text-center tabular-nums ${input ? 'text-sky-400' : ''}`}>
                        {text(r)}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="border-t-2 border-gray-300 font-semibold" data-testid="weekly-total">
                  <td className="px-3 py-1.5">{filtering ? 'Selected pods' : 'All pods'}</td>
                  <td />
                  {COLS.map(([label, text]) => (
                    <td key={label} className="px-3 py-1.5 text-center tabular-nums">
                      {text(total ?? data.total)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Page>
  );
}
