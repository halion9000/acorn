'use client';

/**
 * Metrics > Weekly Tech Comparison: one week, each engineer under their pod: days worked, tickets new, opened and closed in the week, older tickets closed, closed in all, net (closed less new), new and closed per day worked,
 * and the Dialpad call tickets left out of those counts; and a line for all pods. Days worked is Monday to Friday less full days off and holidays (Rippling).
 */
import { useState } from 'react';

import { NothingYet, Page, selectClass, useMetric } from './kit';

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
  const { data, denied, problem } = useMetric<Report>(`/api/v1/reports/metrics/weekly-comparison${week ? `?week=${week}` : ''}`);
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
          {!data.has_detail && (
            <p className="text-sm text-amber-300" role="status">
              CORE has not sent the weekly ticket counts for this week yet; they arrive with its next daily round.
            </p>
          )}
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm" data-testid="weekly-comparison">
              <thead style={{ background: '#1f4e79' }} className="text-xs font-semibold text-white">
                <tr>
                  <th className="px-3 py-2 text-left">Pod</th>
                  <th className="px-3 py-2 text-left">Tech</th>
                  {COLS.map(([label]) => (
                    <th key={label} className="px-3 py-2 text-center">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {data.rows.map((r, i) => (
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
                  <td className="px-3 py-1.5">All pods</td>
                  <td />
                  {COLS.map(([label, text]) => (
                    <td key={label} className="px-3 py-1.5 text-center tabular-nums">
                      {text(data.total)}
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
