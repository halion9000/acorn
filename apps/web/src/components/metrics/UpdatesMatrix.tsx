'use client';

import { Fragment } from 'react';

export interface UpdateDetail {
  comments: number;
  updated: number;
  resolved: number;
}
export interface UpdateRow {
  engineer: string;
  detail?: Record<string, UpdateDetail>;
}

export const UPDATE_COLS = [
  { key: 'comments', label: 'Comments Added', color: '#00d4ff' },
  { key: 'updated', label: 'Tickets Updated', color: '#b0b8bd' },
  { key: 'resolved', label: 'Tickets Resolved', color: '#f5c400' },
] as const;

/** The widest each column gets across everyone, so a bar's length means the same thing down a column (pure). */
export function columnMax(rows: UpdateRow[], weeks: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const w of weeks) for (const c of UPDATE_COLS) out[`${w}|${c.key}`] = Math.max(1, ...rows.map((r) => r.detail?.[w]?.[c.key] ?? 0));
  return out;
}

const weekTitle = (w: string): string => {
  const [y, m, d] = w.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d)).toLocaleString('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' });
};

function Pill({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div className="relative mx-auto h-5 w-28 overflow-hidden rounded-full border border-gray-600" style={{ background: 'rgba(0,0,0,0.25)' }}>
      <div data-testid="pill-fill" className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${value > 0 ? Math.max(8, (value / max) * 100) : 0}%`, background: color, opacity: 0.85 }} />
      <span className="relative flex h-full items-center justify-center text-[11px] font-semibold tabular-nums" style={{ color: '#fff', textShadow: '0 0 3px #000' }}>
        {value}
      </span>
    </div>
  );
}

/** Each team member by week, three bars per week: comments added, tickets updated and tickets resolved. */
export function UpdatesMatrix({ weeks, rows }: { weeks: string[]; rows: UpdateRow[] }) {
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const max = columnMax(rows, weeks);
  const sorted = [...rows].sort((a, b) => a.engineer.localeCompare(b.engineer));
  return (
    <div className="max-h-[36rem] overflow-auto" data-testid="updates-matrix">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead className="sticky top-0 z-10" style={{ background: '#1f2f33' }}>
          <tr>
            <th rowSpan={2} className="sticky left-0 min-w-[10rem] px-4 py-2 text-left font-semibold" style={{ background: '#1f2f33' }}>
              Team Member
            </th>
            {weeks.map((w) => (
              <th key={w} colSpan={UPDATE_COLS.length} className="border-l border-gray-700 px-3 py-2 text-center font-semibold">
                {weekTitle(w)}
              </th>
            ))}
          </tr>
          <tr>
            {weeks.map((w) => (
              <Fragment key={w}>
                {UPDATE_COLS.map((c, i) => (
                  <th key={c.key} className={`${i === 0 ? 'border-l border-gray-700 ' : ''}px-2 py-1 text-center text-[11px] font-semibold`}>
                    {c.label}
                  </th>
                ))}
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.engineer} className="border-t border-gray-800">
              <td className="sticky left-0 whitespace-nowrap px-4 py-1.5 font-medium" style={{ background: '#243236' }}>
                {r.engineer}
              </td>
              {weeks.map((w) => (
                <Fragment key={w}>
                  {UPDATE_COLS.map((c, i) => (
                    <td key={c.key} className={`${i === 0 ? 'border-l border-gray-800 ' : ''}px-2 py-1.5`}>
                      <Pill value={r.detail?.[w]?.[c.key] ?? 0} max={max[`${w}|${c.key}`]!} color={c.color} />
                    </td>
                  ))}
                </Fragment>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
