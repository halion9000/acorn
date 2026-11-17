'use client';

/**
 * Sales and Finance > Profitability: for one month, what each client was invoiced, the hours worked for them, what those hours cost and what is left after labor. The numbers come from the HaloPSA summary
 * CORE sends about once a day. Software, hardware, travel and overhead are not in it (the page says so). Needs the finance permission; without it the API answers 403 and this says so.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { saveText } from '@/lib/saveFile';
import { ClientProfitDetail } from './ClientProfitDetail';

interface Row {
  client_id: string;
  client_name: string;
  revenue: number;
  invoices: number;
  hours: number;
  labor: number;
  after_labor: number;
  margin_percent: number | null;
  software_per_run: number | null;
}
interface Report {
  month: string;
  rows: Row[];
  totals: { revenue: number; labor: number; after_labor: number; hours: number; margin_percent: number | null };
  unmatched_hours: { client: string; hours: number; labor: number }[];
  agents_on_default_rate: { agent_id: string; name: string; hours: number }[];
  default_rate: number;
}
interface Rate {
  scope: 'agent' | 'team' | 'default';
  key: string;
  hourly_rate: number;
}
interface Agent {
  id: string;
  name: string;
  team: string;
  active: boolean;
}
interface Profitability {
  received_at: string | null;
  months: string[];
  report: Report | null;
  rates: Rate[];
  agents?: Agent[];
  note?: string;
}

export const money = (n: number | null | undefined): string => (n === null || n === undefined ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }));
export const pct = (v: number | null): string => (v === null ? '—' : `${v}%`);
export const monthLabel = (m: string): string => {
  const [y, mo] = m.split('-').map(Number) as [number, number];
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
};
export type SortKey = 'client_name' | 'revenue' | 'hours' | 'labor' | 'after_labor' | 'margin_percent';
/** The rows in the order the person chose (pure); a missing margin sorts last either way. */
export function sortRows(rows: Row[], key: SortKey, desc: boolean): Row[] {
  const dir = desc ? -1 : 1;
  return [...rows].sort((a, b) => {
    const x = a[key];
    const y = b[key];
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return (typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number)) * dir;
  });
}

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function ProfitabilityView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [data, setData] = useState<Profitability | null>(null);
  const [month, setMonth] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'revenue', desc: true });
  const [scope, setScope] = useState<Rate['scope']>('default');
  const [key, setKey] = useState('');
  const [rate, setRate] = useState('');
  const [busy, setBusy] = useState(false);
  // The client whose numbers are opened below the table.
  const [openClient, setOpenClient] = useState<string | null>(null);

  const load = useCallback(async (m: string) => {
    try {
      const res = await authFetch(m ? `/api/v1/finance/profitability?month=${encodeURIComponent(m)}` : '/api/v1/finance/profitability');
      if (res.status === 403) {
        setDenied(true);
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const body = (await res.json()) as Profitability;
      setData(body);
      if (body.report && body.report.month !== m) setMonth(body.report.month);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load('');
  }, [load]);

  const teams = useMemo(() => [...new Set((data?.agents ?? []).map((a) => a.team).filter(Boolean))].sort(), [data]);
  const rows = useMemo(() => (data?.report ? sortRows(data.report.rows, sort.key, sort.desc) : []), [data, sort]);

  const saveRate = async () => {
    setBusy(true);
    try {
      const res = await authFetch('/api/v1/finance/labor-rates', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope, key: scope === 'default' ? '' : key, hourly_rate: rate }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setRate('');
      await load(month);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  };
  const removeRate = async (r: Rate) => {
    setBusy(true);
    try {
      const res = await authFetch(`/api/v1/finance/labor-rates?scope=${r.scope}&key=${encodeURIComponent(r.key)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      await load(month);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not remove');
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    const res = await authFetch(`/api/v1/finance/profitability/export.csv?month=${encodeURIComponent(month)}`);
    if (res.ok) saveText(`profitability-${month}.csv`, await res.text());
    else setProblem(`The API answered ${res.status}`);
  };
  const head = (k: SortKey, label: string) => (
    <th className="px-3 py-2">
      <button type="button" className="uppercase" onClick={() => setSort({ key: k, desc: sort.key === k ? !sort.desc : k !== 'client_name' })}>
        {label}
        {sort.key === k ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  );

  if (denied) return <p className="p-6 text-sm text-amber-300">Profitability shows money, so it needs the finance permission. Ask the owner to add it to your role.</p>;
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Profitability</h1>
        <p className="mt-1 text-sm text-gray-400">What each client was invoiced, the hours worked for them and what is left after labor, from HaloPSA. Updated about once a day.</p>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {data && data.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="profit-empty">
          Nothing has arrived from HaloPSA yet. CORE sends the summary about once a day once HaloPSA is connected in CORE.
        </p>
      )}
      {data?.report && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-300">
              Month
              <select aria-label="Month" className={input} value={month} onChange={(e) => { setMonth(e.target.value); void load(e.target.value); }}>
                {[...data.months].reverse().map((m) => (
                  <option key={m} value={m}>
                    {monthLabel(m)}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className={ghost} onClick={() => void download()}>
              Export CSV
            </button>
            <span className="text-xs text-gray-500">Last read {data.received_at ? new Date(data.received_at).toLocaleString() : ''}</span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="profit-totals">
            {[
              ['Revenue', money(data.report.totals.revenue)],
              ['Labor', money(data.report.totals.labor)],
              ['After labor', money(data.report.totals.after_labor)],
              ['Margin after labor', pct(data.report.totals.margin_percent)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-gray-700 bg-gray-800 p-3">
                <p className="text-xl font-semibold text-white">{value}</p>
                <p className="text-xs text-gray-400">{label}</p>
              </div>
            ))}
          </div>
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm" data-testid="profit-table">
              <thead className="bg-gray-900/60 text-xs text-gray-500">
                <tr>
                  {head('client_name', 'Client')}
                  {head('revenue', 'Revenue')}
                  {head('hours', 'Hours')}
                  {head('labor', 'Labor')}
                  {head('after_labor', 'After labor')}
                  {head('margin_percent', 'Margin')}
                  <th className="px-3 py-2 uppercase">Software per run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {rows.map((r) => (
                  <tr key={r.client_id} data-testid="profit-row">
                    <td className="px-3 py-2 text-gray-100">
                      <button type="button" className="text-left text-blue-300 hover:underline" aria-label={`Where the numbers of ${r.client_name} come from`} onClick={() => setOpenClient(r.client_id)}>
                        {r.client_name}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-gray-300">{money(r.revenue)}</td>
                    <td className="px-3 py-2 text-gray-300">{r.hours}</td>
                    <td className="px-3 py-2 text-gray-300">{money(r.labor)}</td>
                    <td className={`px-3 py-2 ${r.after_labor < 0 ? 'text-red-300' : 'text-gray-100'}`}>{money(r.after_labor)}</td>
                    <td className={`px-3 py-2 ${r.margin_percent !== null && r.margin_percent < 0 ? 'text-red-300' : 'text-gray-300'}`}>{pct(r.margin_percent)}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">{money(r.software_per_run)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {openClient && <ClientProfitDetail clientId={openClient} month={data.report.month} onClose={() => setOpenClient(null)} />}
          {data.note && <p className="text-xs text-gray-500">{data.note}</p>}
          {data.report.unmatched_hours.length > 0 && (
            <section className="rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="profit-unmatched">
              <h2 className="text-sm font-semibold text-gray-200">Hours with no invoiced client this month</h2>
              <p className="text-xs text-gray-500">Time logged for a client that was not invoiced in {monthLabel(data.report.month)} (no-charge work, or a name that differs from the invoice).</p>
              <ul className="mt-2 text-sm text-gray-300">
                {data.report.unmatched_hours.slice(0, 15).map((u) => (
                  <li key={u.client}>
                    {u.client}: {u.hours} h, {money(u.labor)}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {data && data.received_at !== null && (
        <section className="space-y-2 rounded-lg border border-gray-700 bg-gray-900/60 p-4" aria-label="Hourly labor cost">
          <h2 className="text-sm font-semibold text-gray-200">What an hour costs</h2>
          <p className="text-xs text-gray-500">
            The default is {money(data.report?.default_rate ?? 65)} an hour until you set one. A rate for an agent beats one for their team, which beats the default.
          </p>
          {data.report && data.report.agents_on_default_rate.length > 0 && (
            <p className="text-xs text-amber-300" data-testid="profit-default-agents">
              On the default rate this month: {data.report.agents_on_default_rate.slice(0, 8).map((a) => `${a.name} (${a.hours} h)`).join(', ')}
            </p>
          )}
          <ul className="text-sm text-gray-300" data-testid="profit-rates">
            {data.rates.map((r) => (
              <li key={`${r.scope}:${r.key}`} className="flex items-center gap-2">
                <span className="w-56">
                  {r.scope === 'default' ? 'Everyone (default)' : r.scope === 'team' ? `Team: ${r.key}` : `Agent: ${data.agents?.find((a) => a.id === r.key)?.name ?? r.key}`}
                </span>
                <span>{money(r.hourly_rate)}</span>
                <button type="button" className={ghost} disabled={busy} onClick={() => void removeRate(r)}>
                  Remove
                </button>
              </li>
            ))}
            {data.rates.length === 0 && <li className="text-gray-500">No rates set.</li>}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Rate for" className={input} value={scope} onChange={(e) => { setScope(e.target.value as Rate['scope']); setKey(''); }}>
              <option value="default">Everyone</option>
              <option value="team">A team</option>
              <option value="agent">One agent</option>
            </select>
            {scope === 'team' && (
              <select aria-label="Team" className={input} value={key} onChange={(e) => setKey(e.target.value)}>
                <option value="">Pick a team</option>
                {teams.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            )}
            {scope === 'agent' && (
              <select aria-label="Agent" className={input} value={key} onChange={(e) => setKey(e.target.value)}>
                <option value="">Pick an agent</option>
                {(data.agents ?? []).filter((a) => a.active).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            )}
            <input aria-label="Hourly cost" className={`${input} w-28`} inputMode="decimal" placeholder="Per hour" value={rate} onChange={(e) => setRate(e.target.value)} />
            <button type="button" className={ghost} disabled={busy || !rate || (scope !== 'default' && !key)} onClick={() => void saveRate()}>
              Save rate
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
