'use client';

import { Fragment, useMemo, useState } from 'react';

export interface PodRow {
  week: string;
  pod: string;
  engineer: string;
  resolved: number;
  created: number;
  logged_hours: number;
  days_off: number;
  holidays: number;
}

export interface Sums {
  resolved: number;
  created: number;
  base: number;
  timeOff: number;
  holidays: number;
  available: number;
  logged: number;
}

export const BASE_HOURS = 40;
const r2 = (n: number): number => Math.round(n * 100) / 100;

/** One engineer's week: a 40-hour week less time off and holidays (both in hours), the hours logged, and the tickets. A week with nothing left to work is no data (null), as Rewst counts it. */
export function weekSums(row: PodRow | undefined): Sums | null {
  if (!row) return null;
  const available = BASE_HOURS - row.days_off - row.holidays;
  if (available <= 0) return null;
  return { resolved: row.resolved, created: row.created, base: BASE_HOURS, timeOff: row.days_off, holidays: row.holidays, available, logged: r2(row.logged_hours) };
}

/** Adds weeks (and people) together; null when none has data. */
export function addSums(list: (Sums | null)[]): Sums | null {
  const valid = list.filter((x): x is Sums => x !== null);
  if (valid.length === 0) return null;
  const out = valid.reduce((a, b) => ({ resolved: a.resolved + b.resolved, created: a.created + b.created, base: a.base + b.base, timeOff: a.timeOff + b.timeOff, holidays: a.holidays + b.holidays, available: a.available + b.available, logged: a.logged + b.logged }));
  return { ...out, available: r2(out.available), logged: r2(out.logged) };
}

/** Logged over available hours, or null with nothing available. */
export const utilization = (s: Sums | null): number | null => (s && s.available > 0 ? s.logged / s.available : null);

/** The colour band of a utilization: 80% and over is high, 50% and over medium, the rest (and none) low. */
export function utilBand(v: number | null): 'high' | 'med' | 'low' {
  return v === null || v < 0.5 ? 'low' : v >= 0.8 ? 'high' : 'med';
}

const BAND: Record<'high' | 'med' | 'low', { bg: string; fg: string }> = {
  high: { bg: 'rgba(34,197,94,0.22)', fg: '#4ade80' },
  med: { bg: 'rgba(245,158,11,0.22)', fg: '#fbbf24' },
  low: { bg: 'rgba(239,68,68,0.22)', fg: '#f87171' },
};

/** The text shown over a utilization cell: how the percentage was worked out. */
export function utilTip(s: Sums): string {
  const u = utilization(s);
  return [`Logged hours ${r2(s.logged)}`, `Base hours ${r2(s.base)}`, `Time off -${r2(s.timeOff)} h`, `Holidays -${r2(s.holidays)} h`, `Available hours ${r2(s.available)}`, `Utilization ${u === null ? '-' : (u * 100).toFixed(1)}% = ${r2(s.logged)} / ${r2(s.available)}`].join('\n');
}

const COLS = ['Resolved Tickets', 'Created Tickets', 'Available Hours', 'Logged Hours', 'Utilization'] as const;
const monthOf = (week: string): string => week.slice(0, 7);
const monthLabel = (ym: string): string => {
  const [y, m] = ym.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
};
const weekLabel = (w: string): string => {
  const [y, m, d] = w.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d)).toLocaleString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
};

export interface Slot {
  month: string;
  week: string | null; // null: the month total
}

/** The columns across: for each month its weeks, then its month total. */
export function slotsFor(weeks: string[]): Slot[] {
  const months = [...new Set(weeks.map(monthOf))].sort();
  return months.flatMap((m) => [...weeks.filter((w) => monthOf(w) === m).sort().map((w) => ({ month: m, week: w })), { month: m, week: null }]);
}

/** One group of people (a pod, or everyone) in one slot. */
export function groupSums(rows: PodRow[], people: string[], slot: Slot, weeks: string[]): Sums | null {
  const inSlot = weeks.filter((w) => (slot.week === null ? monthOf(w) === slot.month : w === slot.week));
  const byKey = new Map(rows.map((r) => [`${r.week}|${r.engineer}`, r]));
  return addSums(people.flatMap((p) => inSlot.map((w) => weekSums(byKey.get(`${w}|${p}`)))));
}

function Cells({ s }: { s: Sums | null }) {
  const u = utilization(s);
  const band = BAND[utilBand(u)];
  return (
    <>
      <td className="border-l border-gray-800 px-2 py-1.5 text-center tabular-nums">{s ? Math.round(s.resolved) : '—'}</td>
      <td className="px-2 py-1.5 text-center tabular-nums">{s ? Math.round(s.created) : '—'}</td>
      <td className="px-2 py-1.5 text-center tabular-nums">{s ? r2(s.available) : '—'}</td>
      <td className="px-2 py-1.5 text-center tabular-nums">{s ? r2(s.logged) : '—'}</td>
      <td className="px-2 py-1.5 text-center">
        {s && u !== null ? (
          <span title={utilTip(s)} className="rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums" style={{ background: band.bg, color: band.fg }}>
            {(u * 100).toFixed(1)}%
          </span>
        ) : (
          '—'
        )}
      </td>
    </>
  );
}

export function PodsMatrix({ rows, weeks }: { rows: PodRow[]; weeks: string[] }) {
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const slots = useMemo(() => slotsFor(weeks), [weeks]);
  const months = [...new Set(slots.map((s) => s.month))];
  const pods = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const r of rows) map.set(r.pod, (map.get(r.pod) ?? new Set()).add(r.engineer));
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([pod, people]) => ({ pod, people: [...people].sort((a, b) => a.localeCompare(b)) }));
  }, [rows]);
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const everyone = pods.flatMap((p) => p.people);
  return (
    <div className="max-h-[36rem] overflow-auto" data-testid="pods-matrix">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead className="sticky top-0 z-10" style={{ background: '#1f2f33' }}>
          <tr>
            <th rowSpan={3} className="sticky left-0 min-w-[14rem] px-4 py-2 text-left font-semibold" style={{ background: '#1f2f33' }}>
              Sub Team
            </th>
            {months.map((m) => (
              <th key={m} colSpan={slots.filter((s) => s.month === m).length * COLS.length} className="border-l border-gray-700 px-3 py-2 text-center font-semibold">
                {monthLabel(m)}
              </th>
            ))}
          </tr>
          <tr>
            {slots.map((s) => (
              <th key={`${s.month}-${s.week ?? 'total'}`} colSpan={COLS.length} className="border-l border-gray-700 px-3 py-1.5 text-center text-xs font-semibold">
                {s.week ? weekLabel(s.week) : 'Month Total'}
              </th>
            ))}
          </tr>
          <tr>
            {slots.map((s) => (
              <Fragment key={`${s.month}-${s.week ?? 'total'}`}>
                {COLS.map((c, i) => (
                  <th key={c} className={`${i === 0 ? 'border-l border-gray-700 ' : ''}px-2 py-1 text-center text-[11px] font-semibold`}>
                    {c}
                  </th>
                ))}
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {pods.map((p) => (
            <Fragment key={p.pod}>
              <tr className="border-t border-gray-700" style={{ background: 'rgba(255,255,255,0.06)' }}>
                <td className="sticky left-0 px-4 py-2 font-semibold" style={{ background: '#2c3d41' }}>
                  <button type="button" aria-expanded={!closed[p.pod]} onClick={() => setClosed({ ...closed, [p.pod]: !closed[p.pod] })} className="flex items-center gap-2 text-left">
                    <span aria-hidden className="text-xs text-gray-400">
                      {closed[p.pod] ? '▸' : '▾'}
                    </span>
                    {p.pod}
                    <span className="text-xs font-normal text-gray-400">({p.people.length})</span>
                  </button>
                </td>
                {slots.map((s) => (
                  <Cells key={`${s.month}-${s.week ?? 'total'}`} s={groupSums(rows, p.people, s, weeks)} />
                ))}
              </tr>
              {!closed[p.pod] &&
                p.people.map((name) => (
                  <tr key={`${p.pod}|${name}`} className="border-t border-gray-800">
                    <td className="sticky left-0 whitespace-nowrap py-1.5 pl-9 pr-4" style={{ background: '#243236' }}>
                      {name}
                    </td>
                    {slots.map((s) => (
                      <Cells key={`${s.month}-${s.week ?? 'total'}`} s={groupSums(rows, [name], s, weeks)} />
                    ))}
                  </tr>
                ))}
            </Fragment>
          ))}
          <tr className="border-t-2 border-gray-600 font-semibold" style={{ background: 'rgba(255,255,255,0.08)' }}>
            <td className="sticky left-0 px-4 py-2" style={{ background: '#31464a' }}>
              All Pods
            </td>
            {slots.map((s) => (
              <Cells key={`${s.month}-${s.week ?? 'total'}`} s={groupSums(rows, everyone, s, weeks)} />
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
