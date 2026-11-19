'use client';

/**
 * Metrics > Labor hours (the Rewst Labor Hours page, rebuilt): hours worked on tickets by month, by engineer, by client and by ticket type, for all clients or one, over the last 1, 3, 6 or 12 months.
 * Hours only (no rates or money). They come from the HaloPSA summary CORE sends about once a day and are read from A.C.O.R.N's own database, never live from HaloPSA.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { Columns, Panel, PeriodPicker, Table, monthShort, num, periodQuery, selectClass, usePeriod, type CustomRange } from './kit';
import { PageHeader } from '@/components/ui/kit';

interface Summary {
  months: string[];
  total_hours: number;
  hours_per_month: number | null;
  clients: string[];
  by_month: { month: string; hours: number }[];
  by_agent: { agent_id: string; name: string; team?: string; hours: number }[];
  engineers?: { name: string; team: string; total: number; by_month: Record<string, number> }[];
  teams?: string[];
  client_months?: { client: string; total: number; by_month: Record<string, number> }[];
  type_months?: { type: string; total: number; by_month: Record<string, number> }[];
  by_client: { client: string; hours: number }[];
  by_type: { type: string; hours: number }[];
}
interface LaborData {
  received_at: string | null;
  summary: Summary | null;
}

export const PERIODS = [1, 3, 6, 12, 24, 36] as const;
export const hoursText = (n: number | null | undefined): string => (n === null || n === undefined ? '—' : `${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} h`);
export const monthName = (m: string): string => {
  const [y, mo] = m.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' });
};
/** A row's share of the total as a whole percent for a bar width (pure); 0 when there is no total. */
export const widthPercent = (hours: number, total: number): number => (total > 0 ? Math.max(1, Math.round((hours / total) * 100)) : 0);

const pill = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? 'border-blue-500 bg-blue-500/20 text-blue-200' : 'border-gray-700 text-gray-300 hover:bg-gray-800'}`;

export function LaborHoursView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const period = usePeriod(3);
  const [client, setClient] = useState('');
  const [team, setTeam] = useState('');
  const [data, setData] = useState<LaborData | null>(null);

  const load = useCallback(async (m: number, range: CustomRange | null, c: string) => {
    try {
      const res = await authFetch(`/api/v1/reports/ticket-metrics/labor-hours?${periodQuery(m, range)}${c ? `&client=${encodeURIComponent(c)}` : ''}`);
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
    void load(period.months, period.range, client);
  }, [load, period.months, period.range, client]);

  if (denied) return <p className="p-6 text-sm text-amber-300">Labor hours need the metrics permission. Ask the owner to add it to your role.</p>;
  const s = data?.summary;
  return (
    <div className="space-y-4 p-6">
      <PageHeader title="Labor Hours" subtitle="Hours worked on tickets, by month, engineer, client and ticket type. Updated about once a day." />
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
        <PeriodPicker period={period} options={PERIODS} />
      </div>
      {data && data.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="labor-empty">
          Nothing has arrived from HaloPSA yet. CORE sends the hours about once a day once HaloPSA is connected in CORE.
        </p>
      )}
      {s && data?.received_at && (
        <div className="space-y-4">
          <Panel title="Total Hours By Month" testId="by-month">
            <Columns points={s.by_month.map((r) => ({ label: monthShort(r.month), value: r.hours }))} unit=" h" />
          </Panel>
          <Panel title="Labor Hours by Engineer" testId="by-agent">
            <label className="mb-3 flex items-center gap-2 text-sm text-gray-300">
              Team
              <select aria-label="Team" className={selectClass} value={team} onChange={(e) => setTeam(e.target.value)}>
                <option value="">All Teams</option>
                {(s.teams ?? []).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <Table head={['Engineer', 'Team', ...s.months.map(monthShort)]} rows={(s.engineers ?? []).filter((e) => !team || e.team === team).map((e) => [e.name, e.team || 'Unknown', ...s.months.map((m) => num(e.by_month[m] ?? 0, 2))])} />
          </Panel>
          <Panel title="Labor Hours by Client" testId="by-client">
            <Table head={['Client', ...s.months.map(monthShort)]} rows={(s.client_months ?? []).map((c) => [c.client, ...s.months.map((m) => num(c.by_month[m] ?? 0, 2))])} />
          </Panel>
          <Panel title="Labor Hours by Ticket Type" testId="by-type">
            <Table head={['Ticket Type', ...s.months.map(monthShort)]} rows={(s.type_months ?? []).map((t) => [t.type, ...s.months.map((m) => num(t.by_month[m] ?? 0, 2))])} />
          </Panel>
        </div>
      )}
    </div>
  );
}
