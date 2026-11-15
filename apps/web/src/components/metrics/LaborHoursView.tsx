'use client';

/**
 * Metrics > Labor hours (the Rewst Labor Hours page, rebuilt): hours worked on tickets by month, by engineer, by client and by ticket type, for all clients or one, over the last 1, 3, 6 or 12 months.
 * Hours only (no rates or money). They come from the HaloPSA summary CORE sends about once a day and are read from A.C.O.R.N's own database, never live from HaloPSA.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

interface Summary {
  months: string[];
  total_hours: number;
  hours_per_month: number | null;
  clients: string[];
  by_month: { month: string; hours: number }[];
  by_agent: { agent_id: string; name: string; hours: number }[];
  by_client: { client: string; hours: number }[];
  by_type: { type: string; hours: number }[];
}
interface LaborData {
  received_at: string | null;
  summary: Summary | null;
}

export const PERIODS = [1, 3, 6, 12] as const;
export const hoursText = (n: number | null | undefined): string => (n === null || n === undefined ? '—' : `${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} h`);
export const monthName = (m: string): string => {
  const [y, mo] = m.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' });
};
/** A row's share of the total as a whole percent for a bar width (pure); 0 when there is no total. */
export const widthPercent = (hours: number, total: number): number => (total > 0 ? Math.max(1, Math.round((hours / total) * 100)) : 0);

const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;

function Bars({ title, rows, total, testId }: { title: string; rows: { label: string; hours: number }[]; total: number; testId: string }) {
  return (
    <section className="rounded-lg border border-gray-700 bg-gray-800 p-3" data-testid={testId}>
      <h2 className="mb-2 text-sm font-semibold text-white">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">No hours in this period.</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.slice(0, 15).map((r) => (
            <li key={r.label} className="text-sm text-gray-200">
              <div className="flex justify-between gap-3">
                <span className="truncate">{r.label}</span>
                <span className="tabular-nums text-gray-400">{hoursText(r.hours)}</span>
              </div>
              <div className="mt-0.5 h-1.5 rounded bg-gray-700">
                <div className="h-1.5 rounded bg-blue-500" style={{ width: `${widthPercent(r.hours, total)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 15 && <p className="mt-2 text-xs text-gray-500">The {rows.length - 15} smallest are not shown.</p>}
    </section>
  );
}

export function LaborHoursView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [months, setMonths] = useState<number>(3);
  const [client, setClient] = useState('');
  const [data, setData] = useState<LaborData | null>(null);

  const load = useCallback(async (m: number, c: string) => {
    try {
      const res = await authFetch(`/api/v1/reports/ticket-metrics/labor-hours?months=${m}${c ? `&client=${encodeURIComponent(c)}` : ''}`);
      if (res.status === 403) {
        setDenied(true);
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setData((await res.json()) as LaborData);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load(months, client);
  }, [load, months, client]);

  if (denied) return <p className="p-6 text-sm text-amber-300">Labor hours need the metrics permission. Ask the owner to add it to your role.</p>;
  const s = data?.summary;
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Labor hours</h1>
        <p className="mt-1 text-sm text-gray-400">Hours worked on tickets, by month, engineer, client and ticket type. Updated about once a day.</p>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Client
          <select aria-label="Client" className="rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100" value={client} onChange={(e) => setClient(e.target.value)}>
            <option value="">All clients</option>
            {(s?.clients ?? []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Period" className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={months === p} className={pill(months === p)} onClick={() => setMonths(p)}>
              {p === 1 ? 'Last month' : `Last ${p} months`}
            </button>
          ))}
        </div>
      </div>
      {data && data.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="labor-empty">
          Nothing has arrived from HaloPSA yet. CORE sends the hours about once a day once HaloPSA is connected in CORE.
        </p>
      )}
      {s && data?.received_at && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="labor-cards">
            {[
              ['Hours worked', hoursText(s.total_hours)],
              ['A month on average', hoursText(s.hours_per_month)],
              ['Engineers', String(s.by_agent.length)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-gray-700 bg-gray-800 p-3">
                <p className="text-xl font-semibold text-white">{value}</p>
                <p className="text-xs text-gray-400">{label}</p>
              </div>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Bars testId="by-month" title="By month" total={s.total_hours} rows={s.by_month.map((r) => ({ label: monthName(r.month), hours: r.hours }))} />
            <Bars testId="by-type" title="By ticket type" total={s.total_hours} rows={s.by_type.map((r) => ({ label: r.type, hours: r.hours }))} />
            <Bars testId="by-agent" title="By engineer" total={s.total_hours} rows={s.by_agent.map((r) => ({ label: r.name, hours: r.hours }))} />
            <Bars testId="by-client" title="By client" total={s.total_hours} rows={s.by_client.map((r) => ({ label: r.client, hours: r.hours }))} />
          </div>
        </>
      )}
    </div>
  );
}
