'use client';

/**
 * The pieces every Metrics page shares (the Rewst metric dashboards, rebuilt): fetching one page's numbers, the period buttons, panels, a bar list, a column chart and a plain table. The numbers come from
 * A.C.O.R.N's own database, which CORE fills about once a day; a page shows "nothing has arrived yet" until then.
 */
import { useEffect, useState, type ReactNode } from 'react';

import { authFetch } from '@/lib/auth-session';
import { MonthYearPicker } from '@/components/ui/MonthYearPicker';
import { PageHeader, Segmented, SkeletonRows, StatCard } from '@/components/ui/kit';

export interface MetricState<T> {
  data: T | null;
  denied: boolean;
  problem: string | null;
}

/** Fetches one Metrics page's numbers again whenever the address changes (a new period or filter). A 403 means the person lacks the metrics permission. */
export function useMetric<T>(path: string): MetricState<T> {
  const [state, setState] = useState<MetricState<T>>({ data: null, denied: false, problem: null });
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch(path);
        if (!live) return;
        if (res.status === 403) return setState({ data: null, denied: true, problem: null });
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        setState({ data: (await res.json()) as T, denied: false, problem: null });
      } catch (e) {
        if (live) setState((s) => ({ ...s, problem: e instanceof Error ? e.message : 'Could not load' }));
      }
    })();
    return () => {
      live = false;
    };
  }, [path]);
  return state;
}

export const PERIODS = [1, 3, 6, 12] as const;
export const LONG_PERIODS = [3, 6, 12, 24, 36] as const;
export const num = (n: number | null | undefined, digits = 0): string => (n === null || n === undefined ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: digits }));
export const pctText = (n: number | null | undefined): string => (n === null || n === undefined ? '—' : `${n}%`);
export const moneyText = (n: number | null | undefined): string => (n === null || n === undefined ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }));
/** "2026-11-02" as "Nov 2" (the Monday a week starts on). */
export function weekLabel(week: string): string {
  const [y, m, d] = week.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d)).toLocaleString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}
/** "2026-11" as "Nov 26". */
export function monthShort(month: string): string {
  const [y, m] = month.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' });
}
/** A bar's width as a whole percent of the largest value (pure); at least 1 for anything above zero. */
export function barWidth(value: number, max: number): number {
  return max > 0 && value > 0 ? Math.max(1, Math.round((value / max) * 100)) : 0;
}

const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;
export const selectClass = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';

export function Page({ title, subtitle, denied, problem, empty, loading, children }: { title: string; subtitle: string; denied: boolean; problem: string | null; empty: ReactNode; loading?: boolean; children: ReactNode }) {
  if (denied) return <p className="p-6 text-sm text-amber-300">{title} needs the metrics permission. Ask the owner to add it to your role.</p>;
  return (
    <div className="p-6">
      <div className="metrics-shell space-y-4">
      <PageHeader title={title} subtitle={subtitle} />
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {loading && !problem ? (
        <div className="space-y-4" data-testid="metrics-loading">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((n) => (
              <StatCard key={n} label="" value="" loading />
            ))}
          </div>
          <SkeletonRows rows={5} cols={4} />
        </div>
      ) : (
        <>
          {empty}
          {children}
        </>
      )}
      </div>
    </div>
  );
}

export function NothingYet({ show, what }: { show: boolean; what: string }) {
  if (!show) return null;
  return (
    <p className="text-sm text-gray-400" data-testid="nothing-yet">
      Nothing has arrived yet. CORE sends {what} about once a day once the tool is connected in CORE.
    </p>
  );
}

export function Periods({ value, onChange, options = PERIODS }: { value: number; onChange: (n: number) => void; options?: readonly number[] }) {
  return <Segmented label="Period" value={value} onChange={onChange} options={options.map((p) => ({ value: p, label: p === 1 ? 'Last month' : `Last ${p} months` }))} />;
}

export interface CustomRange {
  start: string;
  end: string;
}
export interface PeriodState {
  months: number;
  range: CustomRange | null;
  setMonths: (n: number) => void;
  setRange: (r: CustomRange | null) => void;
  /** What goes in the address: the newest N months, or N plus a custom range (the range wins on the server). */
  query: string;
}

/** The address part for a period: "months=6", or "months=6&start=2025-01&end=2025-06" for a custom range (pure). */
export function periodQuery(months: number, range: CustomRange | null): string {
  return range ? `months=${months}&start=${range.start}&end=${range.end}` : `months=${months}`;
}

/** The newest N months, or a custom range of months. Choosing a number of months clears the range. */
export function usePeriod(initial: number): PeriodState {
  const [months, setMonthsState] = useState<number>(initial);
  const [range, setRange] = useState<CustomRange | null>(null);
  return {
    months,
    range,
    setMonths: (n) => {
      setMonthsState(n);
      setRange(null);
    },
    setRange,
    query: periodQuery(months, range),
  };
}

/** The months from this one back ``count`` months, newest first, as YYYY-MM (pure). */
export function monthsBack(now: Date, count: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
    out.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`);
  }
  return out;
}

/** The period buttons (Last 1, 3, 6 ... months) and a Custom range with a From and a To month, each a Month and a Year dropdown. */
export function PeriodPicker({ period, options = PERIODS }: { period: PeriodState; options?: readonly number[] }) {
  const list = options.includes(1) ? options : [1, ...options];
  const all = monthsBack(new Date(), 60);
  const custom = period.range !== null;
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="period-picker">
      <div role="group" aria-label="Period" className="flex gap-1">
        {list.map((n) => (
          <button key={n} type="button" aria-pressed={!custom && period.months === n} className={pill(!custom && period.months === n)} onClick={() => period.setMonths(n)}>
            {n === 1 ? 'Last month' : `Last ${n} months`}
          </button>
        ))}
        <button type="button" aria-pressed={custom} className={pill(custom)} onClick={() => period.setRange(custom ? null : { start: all[5]!, end: all[0]! })}>
          Custom range
        </button>
      </div>
      {period.range ? (
        <div className="flex flex-wrap items-center gap-2 text-sm text-gray-300">
          <span>From</span>
          <MonthYearPicker name="From" months={all} value={period.range.start} onChange={(m) => period.setRange({ start: m, end: m > period.range!.end ? m : period.range!.end })} className={selectClass} />
          <span>to</span>
          <MonthYearPicker name="To" months={all} value={period.range.end} onChange={(m) => period.setRange({ start: m < period.range!.start ? m : period.range!.start, end: m })} className={selectClass} />
        </div>
      ) : null}
    </div>
  );
}

export function Panel({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section className="metrics-card" data-testid={testId}>
      <h2 className="text-base">{title}</h2>
      {children}
    </section>
  );
}

export function Cards({ items }: { items: [string, string][] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="cards">
      {items.map(([label, value]) => (
        <MetricStat key={label} label={label} value={value} />
      ))}
    </div>
  );
}

export function BarList({ rows, limit = 15 }: { rows: { label: string; value: number; text?: string }[]; limit?: number }) {
  const max = Math.max(0, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  return (
    <ul className="space-y-1.5">
      {rows.slice(0, limit).map((r) => (
        <li key={r.label} className="text-sm text-gray-200">
          <div className="flex justify-between gap-3">
            <span className="truncate">{r.label}</span>
            <span className="tabular-nums text-gray-400">{r.text ?? num(r.value, 1)}</span>
          </div>
          <div className="mt-0.5 h-1.5 rounded bg-gray-700">
            <div className="h-1.5 rounded" style={{ width: `${barWidth(r.value, max)}%`, background: 'var(--metrics-bar-b)' }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A column chart as plain markup: one column per point, labels under it. */
export function Columns({ points, unit = '' }: { points: { label: string; value: number | null }[]; unit?: string }) {
  const max = Math.max(0, ...points.map((p) => p.value ?? 0));
  if (points.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  return (
    <div className="flex items-end gap-1 overflow-x-auto pb-1" role="img" aria-label="Chart">
      {points.map((p) => (
        <div key={p.label} className="flex min-w-[2rem] flex-1 flex-col items-center gap-1" title={`${p.label}: ${p.value === null ? 'none' : `${num(p.value, 1)}${unit}`}`}>
          <span className="text-[10px] tabular-nums text-gray-400">{p.value === null ? '' : num(p.value, 1)}</span>
          <div className="w-full rounded-t" style={{ height: `${Math.max(2, (barWidth(p.value ?? 0, max) / 100) * 96)}px`, opacity: p.value === null ? 0.2 : 1, background: 'var(--metrics-bar-b)' }} />
          <span className="text-[10px] text-gray-500">{p.label}</span>
        </div>
      ))}
    </div>
  );
}

/** One big number with its label under it, the way the Rewst dashboards show a figure. */
export function MetricStat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div data-testid="metric-stat">
      <p className="metrics-stat-value tabular-nums">{value}</p>
      <p className="metrics-stat-label">{label}</p>
      {note ? <p className="text-xs text-gray-500">{note}</p> : null}
    </div>
  );
}

/** The line under the title that says which months are shown and how many the data holds, as the Rewst pages do: "Showing Jul 2026 - Nov 2026 (5 months) - data available Jul 2026 - Nov 2026" (pure). */
export function showingText(months: string[], availableMonths: number): string {
  if (months.length === 0) return 'No months are available yet.';
  const name = (m: string) => {
    const [y, mo] = m.split('-').map(Number) as [number, number];
    return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
  };
  const first = months[0]!;
  const last = months[months.length - 1]!;
  return `Showing ${name(first)} - ${name(last)} (${months.length} month${months.length === 1 ? '' : 's'})${availableMonths > months.length ? ` - ${availableMonths} months of data are held` : ' - that is all the data held'}`;
}

/** The round number a chart axis stops at: the next 1, 2, 5 or 10 times a power of ten above the value (pure). */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(value));
  const f = value / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

const compact = (n: number): string => (n >= 1000 ? `${(Math.round(n / 100) / 10).toString().replace(/\.0$/, '')}k` : String(n));

/** Two columns per label side by side (for example created and resolved by month), with gridlines, the value over each column and a legend. */
export function PairedColumns({ points, aLabel, bLabel }: { points: { label: string; a: number; b: number }[]; aLabel: string; bLabel: string }) {
  if (points.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const top = niceMax(Math.max(...points.flatMap((p) => [p.a, p.b])));
  const lines = [0, 0.25, 0.5, 0.75, 1];
  const height = 220;
  return (
    <div role="img" aria-label={`${aLabel} and ${bLabel} by month`} data-testid="paired-columns">
      <div className="mb-2 flex gap-4 text-xs" style={{ color: 'var(--metrics-soft)' }}>
        <span className="flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--metrics-bar-a)' }} /> {aLabel}
        </span>
        <span className="flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: 'var(--metrics-bar-b)' }} /> {bLabel}
        </span>
      </div>
      <div className="flex gap-2">
        <div className="relative w-9 shrink-0 text-right text-[10px] tabular-nums" style={{ height, color: 'var(--metrics-soft)' }}>
          {lines.map((l) => (
            <span key={l} className="absolute right-0 -translate-y-1/2" style={{ bottom: `${l * 100}%` }}>
              {compact(Math.round(top * l))}
            </span>
          ))}
        </div>
        <div className="relative min-w-0 flex-1 overflow-x-auto">
          <div className="relative flex items-end gap-1" style={{ height, minWidth: points.length * 34 }}>
            {lines.map((l) => (
              <div key={l} className="pointer-events-none absolute left-0 right-0" style={{ bottom: `${l * 100}%`, borderTop: '1px solid var(--metrics-grid)' }} />
            ))}
            {points.map((p) => (
              <div key={p.label} className="relative z-10 flex h-full flex-1 items-end justify-center gap-0.5" title={`${p.label}: ${p.a} ${aLabel.toLowerCase()}, ${p.b} ${bLabel.toLowerCase()}`}>
                {[
                  [p.a, 'var(--metrics-bar-a)'],
                  [p.b, 'var(--metrics-bar-b)'],
                ].map(([v, color], i) => (
                  <div key={i} className="relative w-full max-w-[22px] rounded-t-sm" style={{ height: `${Math.max(1, (Number(v) / top) * 100)}%`, background: String(color) }}>
                    <span className="absolute left-1/2 -translate-x-1/2 whitespace-nowrap rounded px-1 text-[10px] font-semibold tabular-nums" style={{ top: i === 0 ? -16 : 6, background: i === 0 ? 'transparent' : 'var(--metrics-pill)', color: i === 0 ? 'var(--metrics-title)' : 'var(--metrics-pill-text)' }}>
                      {compact(Number(v))}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="mt-1 flex gap-1 text-[11px]" style={{ minWidth: points.length * 34, color: 'var(--metrics-title)' }}>
            {points.map((p) => (
              <span key={p.label} className="flex-1 text-center">
                {p.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** A line chart of one value per label (for example minutes of first response by month) with gridlines, the value over each point and an axis on the left. A month with no value breaks the line. */
export function LineChart({ points, unit = '' }: { points: { label: string; value: number | null }[]; unit?: string }) {
  if (points.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const top = niceMax(Math.max(0, ...points.map((p) => p.value ?? 0)));
  const height = 240;
  const width = 1000;
  const step = width / points.length;
  const x = (i: number) => step * i + step / 2;
  const y = (v: number) => height - (v / top) * height;
  const segments: string[] = [];
  let run: string[] = [];
  points.forEach((p, i) => {
    if (p.value === null) {
      if (run.length > 1) segments.push(run.join(' '));
      run = [];
    } else run.push(`${x(i).toFixed(1)},${y(p.value).toFixed(1)}`);
  });
  if (run.length > 1) segments.push(run.join(' '));
  const lines = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div role="img" aria-label={`Line chart by ${points.length} periods`} data-testid="line-chart" className="flex gap-2">
      <div className="relative w-9 shrink-0 text-right text-[10px] tabular-nums" style={{ height, color: 'var(--metrics-soft)' }}>
        {lines.map((l) => (
          <span key={l} className="absolute right-0 -translate-y-1/2" style={{ bottom: `${l * 100}%` }}>
            {Math.round(top * l * 10) / 10}
          </span>
        ))}
      </div>
      <div className="relative min-w-0 flex-1 overflow-x-auto">
        <div className="relative" style={{ height, minWidth: points.length * 44 }}>
          {lines.map((l) => (
            <div key={l} className="pointer-events-none absolute left-0 right-0" style={{ bottom: `${l * 100}%`, borderTop: '1px solid var(--metrics-grid)' }} />
          ))}
          <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
            {segments.map((seg) => (
              <polyline key={seg} points={seg} fill="none" stroke="var(--metrics-bar-b)" strokeWidth={3} vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
          {points.map((p, i) =>
            p.value === null ? null : (
              <span key={p.label} className="absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded border px-1 text-[10px] font-semibold tabular-nums" style={{ left: `${((i + 0.5) / points.length) * 100}%`, top: `${(y(p.value) / height) * 100}%`, background: 'var(--metrics-pill)', color: 'var(--metrics-pill-text)', borderColor: 'var(--metrics-title)' }}>
                {num(p.value, 2)}
                {unit}
              </span>
            ),
          )}
        </div>
        <div className="mt-1 flex text-[11px]" style={{ minWidth: points.length * 44, color: 'var(--metrics-title)' }}>
          {points.map((p) => (
            <span key={p.label} className="flex-1 text-center">
              {p.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** A cell's value for sorting: a number when it reads as one ("$1,234", "12%", "3.5 h"), else its text in lower case; anything that is not text or a number has none (pure). */
export function sortValue(cell: ReactNode): number | string | null {
  if (typeof cell === 'number') return Number.isFinite(cell) ? cell : null;
  if (typeof cell !== 'string') return null;
  const text = cell.trim();
  if (text === '' || text === '—') return null;
  const n = Number(text.replace(/[$,%\s]/g, '').replace(/(h|hrs?|min|m|k)$/i, ''));
  return Number.isFinite(n) && /\d/.test(text) ? n : text.toLowerCase();
}

/** Rows ordered by one column, empty values last, numbers by size and text A to Z; ``dir`` 0 leaves them as given (pure). */
export function sortedRows(rows: ReactNode[][], col: number, dir: 0 | 1 | -1): ReactNode[][] {
  if (dir === 0) return rows;
  return [...rows].sort((a, b) => {
    const x = sortValue(a[col]);
    const y = sortValue(b[col]);
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    if (typeof x === 'number') return -1;
    if (typeof y === 'number') return 1;
    return x.localeCompare(y) * dir;
  });
}

/** A table whose columns sort when their heading is pressed: first the biggest (or Z to A), then the smallest, then back to the order given. Columns whose cells are not text or numbers do not sort. */
export function Table({ head, rows, testId, firstWide = true }: { head: string[]; rows: ReactNode[][]; testId?: string; firstWide?: boolean }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const shown = sort ? sortedRows(rows, sort.col, sort.dir) : rows;
  const press = (col: number) => {
    const text = col === 0 && firstWide;
    setSort((s) => (s?.col !== col ? { col, dir: text ? 1 : -1 } : s.dir === (text ? 1 : -1) ? { col, dir: text ? -1 : 1 } : null));
  };
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm" data-testid={testId}>
        <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
          <tr>
            {head.map((h, i) => {
              const sortable = rows.some((r) => sortValue(r[i]) !== null);
              const on = sort?.col === i;
              return (
                <th key={`${h}-${i}`} className={`px-3 py-2 ${i === 0 && firstWide ? 'text-left' : 'text-right'}`} aria-sort={on ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                  {sortable ? (
                    <button type="button" onClick={() => press(i)} className="uppercase hover:text-gray-200">
                      <span>{h}</span>
                      <span aria-hidden="true">{on ? (sort.dir === 1 ? ' ▲' : ' ▼') : ' ↕'}</span>
                    </button>
                  ) : (
                    h
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800 text-gray-200">
          {shown.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={`px-3 py-1.5 tabular-nums ${j === 0 && firstWide ? 'text-left' : 'text-right'}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
