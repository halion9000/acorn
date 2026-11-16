'use client';

/**
 * Sales and Finance > Net income: the rest of finance's profitability workbook. For a month, each client from revenue to net income (direct labor, the payroll true-up, software, travel, equipment, hardware,
 * sales and marketing, overhead), then new clients, the summary by industry, hours by function and utilization, and the twelve-month ranking. The cost lines are typed in on the Inputs tab (QuickBooks fills
 * them when it is connected); a cost that has not been entered is zero and the page says which. Needs the finance permission; without it the API answers 403 and this says so.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { money, monthLabel, pct } from './ProfitabilityView';

export interface FullRow {
  client_key: string;
  client_name: string;
  revenue: number;
  hours: number;
  direct_labor: number;
  labor_trueup: number;
  addon_software: number;
  support_software: number;
  travel: number;
  equipment: number;
  hardware: number;
  total_cost: number;
  gross_profit: number;
  gross_margin: number | null;
  sales_marketing: number;
  overhead: number;
  net_income: number;
  net_margin: number | null;
  industry: string;
  non_profit: boolean;
  new_client: boolean;
}
interface Industry {
  industry: string;
  clients: number;
  non_profit_clients: number;
  revenue: number;
  gross_profit: number;
  net_income: number;
  gross_margin: number | null;
  net_margin: number | null;
}
interface HoursReport {
  available_hours_per_person: number;
  total_hours: number;
  by_function: { function: string; billable: boolean; hours: number; cost: number; share_percent: number | null }[];
  by_person: { agent_id: string; name: string; team: string; hours: number; billable_hours: number; utilization_percent: number | null }[];
}
export interface RankRow {
  client_key: string;
  client_name: string;
  revenue: number;
  net_income: number;
  net_margin: number | null;
  rank: number;
  tier: string;
  bottom_20: boolean;
  target_margin: number;
  meets_target: boolean;
}
interface Analysis {
  received_at: string | null;
  months: string[];
  report: {
    month: string;
    rows: FullRow[];
    totals: Record<string, number | null>;
    missing: string[];
    unplaced: Record<string, number>;
    new_clients: { client_key: string; client_name: string; revenue: number }[];
  } | null;
  industries: Industry[];
  hours: HoursReport | null;
  annual: { months: string[]; rows: RankRow[] } | null;
  note?: string;
}
interface Inputs {
  costs: { month: string; category: string; client_name: string; source: string; amount: number; note: string }[];
  master: { client_key: string; client_name: string; industry: string; non_profit: boolean; target_margin: number | null }[];
  available_hours_per_month: number;
  categories: string[];
}

export const CATEGORY_LABELS: Record<string, string> = {
  payroll_cogs: 'Client service payroll (P&L)',
  addon_software: 'Add-on software',
  support_software: 'Support software',
  travel: 'Travel',
  equipment: 'Equipment',
  hardware: 'Hardware',
  sales_marketing: 'Sales and marketing',
  overhead: 'Overhead (G&A)',
};
/** Categories that are one company-wide amount per month, never charged to one client. */
export const COMPANY_WIDE = ['payroll_cogs', 'sales_marketing', 'overhead'];

/** Which parts of the number are not filled in yet, as words for people (pure). */
export function missingNote(missing: string[]): string {
  if (missing.length === 0) return 'Every cost category has an entry for this month.';
  return `Not entered for this month, so counted as zero: ${missing.map((c) => CATEGORY_LABELS[c] ?? c).join(', ')}.`;
}

/** The master sheet as rows, from pasted or uploaded CSV text (pure): name, industry, then non-profit (Non-Profit, yes, true or 1). A header row and blank lines are skipped; quoted cells may hold commas. */
export function parseMasterCsv(text: string): { client_name: string; industry: string; non_profit: boolean; target_margin: null }[] {
  const cells = (line: string): string[] => {
    const out: string[] = [];
    let cur = '';
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]!;
      if (quoted) {
        if (ch === '"' && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else if (ch === '"') quoted = false;
        else cur += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === ',') {
        out.push(cur.trim());
        cur = '';
      } else cur += ch;
    }
    out.push(cur.trim());
    return out;
  };
  const rows: { client_name: string; industry: string; non_profit: boolean; target_margin: null }[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (line.trim() === '') return;
    const [name = '', industry = '', status = ''] = cells(line);
    if (i === 0 && /client|name/i.test(name) && /industry/i.test(industry)) return;
    if (name === '') return;
    rows.push({ client_name: name, industry, non_profit: /^(non-?\s?profit|yes|true|y|1)$/i.test(status), target_margin: null });
  });
  return rows;
}

type Tab = 'net' | 'new' | 'industry' | 'hours' | 'rank' | 'inputs';
const TABS: [Tab, string][] = [
  ['net', 'Revenue to net income'],
  ['new', 'New clients'],
  ['industry', 'By industry'],
  ['hours', 'Hours and utilization'],
  ['rank', 'Ranking'],
  ['inputs', 'Inputs'],
];
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const th = 'px-3 py-2 text-right';
const td = 'px-3 py-1.5 text-right tabular-nums';

export function NetIncomeView() {
  const [denied, setDenied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [data, setData] = useState<Analysis | null>(null);
  const [inputs, setInputs] = useState<Inputs | null>(null);
  const [month, setMonth] = useState('');
  const [tab, setTab] = useState<Tab>('net');
  const [busy, setBusy] = useState(false);
  const [cost, setCost] = useState({ category: 'overhead', client_name: '', amount: '', note: '' });
  const [master, setMaster] = useState({ client_name: '', industry: '', non_profit: false, target_margin: '' });
  const [hoursPer, setHoursPer] = useState('');
  const [importText, setImportText] = useState('');

  const load = useCallback(async (m: string) => {
    try {
      const res = await authFetch(m ? `/api/v1/finance/profitability/analysis?month=${encodeURIComponent(m)}` : '/api/v1/finance/profitability/analysis');
      if (res.status === 403) {
        setDenied(true);
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const body = (await res.json()) as Analysis;
      setData(body);
      if (body.report && body.report.month !== m) setMonth(body.report.month);
      const inRes = await authFetch('/api/v1/finance/profitability/inputs');
      if (inRes.ok) {
        const inBody = (await inRes.json()) as Inputs;
        setInputs(inBody);
        setHoursPer((h) => h || String(inBody.available_hours_per_month));
      }
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load('');
  }, [load]);

  const send = async (url: string, method: 'PUT' | 'DELETE', body?: unknown) => {
    setBusy(true);
    try {
      const res = await authFetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      await load(month);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  if (denied) return <p className="p-6 text-sm text-amber-300">Net income shows money, so it needs the finance permission. Ask the owner to add it to your role.</p>;
  const report = data?.report ?? null;
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Net income</h1>
        <p className="mt-1 text-sm text-gray-400">
          Each client from revenue to net income, after finance&apos;s workbook. Revenue and hours come from HaloPSA about once a day; the cost lines are typed in on the Inputs tab until QuickBooks is connected.
        </p>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {data && data.received_at === null && (
        <p className="text-sm text-gray-400" data-testid="net-empty">
          Nothing has arrived from HaloPSA yet, so there is nothing to work out. The Inputs tab still works: enter what you know and it is used as soon as the first summary arrives.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {report && data && (
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
        )}
        <div className="flex flex-wrap gap-1" role="tablist">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`rounded px-2.5 py-1 text-xs ${tab === id ? 'bg-blue-600 text-white' : 'border border-gray-700 text-gray-300 hover:bg-gray-800'}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'net' && report && (
        <>
          <p className="text-xs text-gray-400" data-testid="missing-note">
            {missingNote(report.missing)}
          </p>
          {Object.keys(report.unplaced).length > 0 && (
            <p className="text-xs text-amber-300" data-testid="unplaced-note">
              No client could carry: {Object.entries(report.unplaced).map(([c, v]) => `${CATEGORY_LABELS[c] ?? c} ${money(v)}`).join(', ')}.
            </p>
          )}
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm" data-testid="net-table">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left">Client</th>
                  {['Revenue', 'Direct labor', 'True-up', 'Add-on sw', 'Support sw', 'Travel', 'Equipment', 'Gross profit', 'Gross %', 'Sales/mktg', 'Overhead', 'Net income', 'Net %'].map((h) => (
                    <th key={h} className={th}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {report.rows.map((r) => (
                  <tr key={r.client_key}>
                    <td className="px-3 py-1.5 text-left">
                      {r.client_name}
                      {r.new_client && <span className="ml-2 rounded bg-emerald-900/50 px-1.5 text-xs text-emerald-200">new</span>}
                    </td>
                    <td className={td}>{money(r.revenue)}</td>
                    <td className={td}>{money(r.direct_labor)}</td>
                    <td className={td}>{money(r.labor_trueup)}</td>
                    <td className={td}>{money(r.addon_software)}</td>
                    <td className={td}>{money(r.support_software)}</td>
                    <td className={td}>{money(r.travel)}</td>
                    <td className={td}>{money(r.equipment)}</td>
                    <td className={td}>{money(r.gross_profit)}</td>
                    <td className={td}>{pct(r.gross_margin)}</td>
                    <td className={td}>{money(r.sales_marketing)}</td>
                    <td className={td}>{money(r.overhead)}</td>
                    <td className={`${td} font-medium ${r.net_income < 0 ? 'text-red-300' : 'text-white'}`}>{money(r.net_income)}</td>
                    <td className={td}>{pct(r.net_margin)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-gray-700 text-gray-100">
                <tr>
                  <td className="px-3 py-2 text-left font-medium">Total</td>
                  {(['revenue', 'direct_labor', 'labor_trueup', 'addon_software', 'support_software', 'travel', 'equipment', 'gross_profit'] as const).map((k) => (
                    <td key={k} className={td}>{money(report.totals[k] as number)}</td>
                  ))}
                  <td className={td}>{pct(report.totals.gross_margin as number | null)}</td>
                  <td className={td}>{money(report.totals.sales_marketing as number)}</td>
                  <td className={td}>{money(report.totals.overhead as number)}</td>
                  <td className={`${td} font-semibold`}>{money(report.totals.net_income as number)}</td>
                  <td className={td}>{pct(report.totals.net_margin as number | null)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          {data?.note && <p className="text-xs text-gray-500">{data.note}</p>}
        </>
      )}

      {tab === 'new' && report && (
        <div data-testid="new-clients">
          {report.new_clients.length === 0 ? (
            <p className="text-sm text-gray-400">No client had its first revenue in {monthLabel(report.month)} (the oldest month the summary holds cannot tell new from existing).</p>
          ) : (
            <ul className="space-y-1 text-sm text-gray-200">
              {report.new_clients.map((c) => (
                <li key={c.client_key}>
                  {c.client_name} <span className="text-gray-500">first month revenue {money(c.revenue)}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-gray-500">The month&apos;s sales and marketing cost is split evenly across these clients.</p>
        </div>
      )}

      {tab === 'industry' && report && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm" data-testid="industry-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left">Industry</th>
                {['Clients', 'Non-profit', 'Revenue', 'Gross profit', 'Gross %', 'Net income', 'Net %'].map((h) => (
                  <th key={h} className={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {data?.industries.map((g) => (
                <tr key={g.industry}>
                  <td className="px-3 py-1.5 text-left">{g.industry}</td>
                  <td className={td}>{g.clients}</td>
                  <td className={td}>{g.non_profit_clients}</td>
                  <td className={td}>{money(g.revenue)}</td>
                  <td className={td}>{money(g.gross_profit)}</td>
                  <td className={td}>{pct(g.gross_margin)}</td>
                  <td className={td}>{money(g.net_income)}</td>
                  <td className={td}>{pct(g.net_margin)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-3 text-xs text-gray-500">Set a client&apos;s industry and non-profit status on the Inputs tab. Clients with none are listed as Unassigned.</p>
        </div>
      )}

      {tab === 'hours' && data?.hours && (
        <div className="space-y-4" data-testid="hours-tab">
          <p className="text-sm text-gray-300">
            {data.hours.total_hours} hours logged in {(month ? monthLabel(month) : 'the month')}. Utilization is billable hours (everything but No Charge) over {data.hours.available_hours_per_person} hours a person can work in a month.
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <table className="w-full text-sm">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left">Function</th>
                  <th className={th}>Hours</th>
                  <th className={th}>Share</th>
                  <th className={th}>Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {data.hours.by_function.map((f) => (
                  <tr key={f.function}>
                    <td className="px-3 py-1.5 text-left">
                      {f.function}
                      {!f.billable && <span className="ml-2 text-xs text-gray-500">not billable</span>}
                    </td>
                    <td className={td}>{f.hours}</td>
                    <td className={td}>{pct(f.share_percent)}</td>
                    <td className={td}>{money(f.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="w-full text-sm">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left">Person</th>
                  <th className={th}>Hours</th>
                  <th className={th}>Billable</th>
                  <th className={th}>Utilization</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {data.hours.by_person.map((p) => (
                  <tr key={p.agent_id}>
                    <td className="px-3 py-1.5 text-left">
                      {p.name}
                      {p.team && <span className="ml-2 text-xs text-gray-500">{p.team}</span>}
                    </td>
                    <td className={td}>{p.hours}</td>
                    <td className={td}>{p.billable_hours}</td>
                    <td className={td}>{pct(p.utilization_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'rank' && data?.annual && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm" data-testid="rank-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left">#</th>
                <th className="px-3 py-2 text-left">Client</th>
                {['Revenue', 'Net income', 'Net %', 'Target', 'Size'].map((h) => (
                  <th key={h} className={th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {data.annual.rows.map((r) => (
                <tr key={r.client_key}>
                  <td className="px-3 py-1.5 text-left">{r.rank}</td>
                  <td className="px-3 py-1.5 text-left">{r.client_name}</td>
                  <td className={td}>{money(r.revenue)}</td>
                  <td className={`${td} ${r.net_income < 0 ? 'text-red-300' : ''}`}>{money(r.net_income)}</td>
                  <td className={`${td} ${r.meets_target ? 'text-emerald-300' : 'text-amber-300'}`}>
                    {pct(r.net_margin)} {r.meets_target ? 'meets' : 'below'} {r.target_margin}%
                  </td>
                  <td className={td}>{r.bottom_20 ? 'Bottom 20' : r.tier}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-3 text-xs text-gray-500">
            The {data.annual.months.length} months to {monthLabel(data.annual.months[data.annual.months.length - 1] ?? month)}, ranked by net income. The target is 20% net unless the client has its own on the Inputs tab.
          </p>
        </div>
      )}

      {tab === 'inputs' && (
        <div className="space-y-6" data-testid="inputs-tab">
          <section>
            <h2 className="mb-2 text-sm font-semibold text-white">Cost for a month</h2>
            <p className="mb-2 text-xs text-gray-500">Name a client to charge it directly; leave the client empty to spread across the month&apos;s clients by revenue. Payroll, sales and marketing and overhead are always company-wide.</p>
            <div className="flex flex-wrap items-end gap-2">
              <select aria-label="Category" className={input} value={cost.category} onChange={(e) => setCost({ ...cost, category: e.target.value })}>
                {(inputs?.categories ?? Object.keys(CATEGORY_LABELS)).filter((c) => c !== 'hardware').map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABELS[c] ?? c}
                  </option>
                ))}
              </select>
              {!COMPANY_WIDE.includes(cost.category) && (
                <input aria-label="Client" className={input} placeholder="Client (optional)" value={cost.client_name} onChange={(e) => setCost({ ...cost, client_name: e.target.value })} />
              )}
              <input aria-label="Amount" className={`${input} w-32`} placeholder="Amount" inputMode="decimal" value={cost.amount} onChange={(e) => setCost({ ...cost, amount: e.target.value })} />
              <button
                type="button"
                className={ghost}
                disabled={busy || !month || cost.amount.trim() === '' || Number.isNaN(Number(cost.amount))}
                onClick={() => void send('/api/v1/finance/profitability/costs', 'PUT', { month, category: cost.category, client_name: COMPANY_WIDE.includes(cost.category) ? '' : cost.client_name, amount: cost.amount, note: cost.note }).then(() => setCost({ ...cost, amount: '' }))}
              >
                Save for {month ? monthLabel(month) : 'the month'}
              </button>
            </div>
            <ul className="mt-3 space-y-1 text-sm text-gray-200">
              {(inputs?.costs ?? []).filter((c) => c.month === month).map((c) => (
                <li key={`${c.category}|${c.client_name}|${c.source}`} className="flex items-center gap-3">
                  <span>
                    {CATEGORY_LABELS[c.category] ?? c.category}
                    {c.client_name ? `, ${c.client_name}` : ''}: {money(c.amount)}
                  </span>
                  <span className="text-xs text-gray-500">{c.source === 'quickbooks' ? 'from QuickBooks' : 'typed'}</span>
                  {c.source === 'manual' && (
                    <button type="button" className={ghost} disabled={busy} onClick={() => void send(`/api/v1/finance/profitability/costs?month=${c.month}&category=${c.category}&client_name=${encodeURIComponent(c.client_name)}`, 'DELETE')}>
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="mb-2 text-sm font-semibold text-white">Client master</h2>
            <div className="flex flex-wrap items-end gap-2">
              <input aria-label="Master client" className={input} placeholder="Client name" value={master.client_name} onChange={(e) => setMaster({ ...master, client_name: e.target.value })} />
              <input aria-label="Industry" className={input} placeholder="Industry" value={master.industry} onChange={(e) => setMaster({ ...master, industry: e.target.value })} />
              <input aria-label="Target net margin" className={`${input} w-28`} placeholder="Target %" inputMode="decimal" value={master.target_margin} onChange={(e) => setMaster({ ...master, target_margin: e.target.value })} />
              <label className="flex items-center gap-1 text-sm text-gray-300">
                <input type="checkbox" checked={master.non_profit} onChange={(e) => setMaster({ ...master, non_profit: e.target.checked })} /> Non-profit
              </label>
              <button
                type="button"
                className={ghost}
                disabled={busy || master.client_name.trim() === ''}
                onClick={() => void send('/api/v1/finance/profitability/clients', 'PUT', { client_name: master.client_name, industry: master.industry, non_profit: master.non_profit, target_margin: master.target_margin.trim() === '' ? null : master.target_margin }).then(() => setMaster({ client_name: '', industry: '', non_profit: false, target_margin: '' }))}
              >
                Save client
              </button>
            </div>
            <ul className="mt-3 space-y-1 text-sm text-gray-200">
              {(inputs?.master ?? []).map((m) => (
                <li key={m.client_key} className="flex items-center gap-3">
                  <span>
                    {m.client_name}: {m.industry || 'no industry'}
                    {m.non_profit ? ', non-profit' : ''}
                    {m.target_margin !== null ? `, target ${m.target_margin}%` : ''}
                  </span>
                  <button type="button" className={ghost} disabled={busy} onClick={() => void send(`/api/v1/finance/profitability/clients?client_name=${encodeURIComponent(m.client_name)}`, 'DELETE')}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="mb-2 text-sm font-semibold text-white">Import the client master</h2>
            <p className="mb-2 text-xs text-gray-500">Paste or choose a CSV with three columns: client, industry, and Non-Profit or For-Profit. Clients already in the master are updated, never duplicated.</p>
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="Client master file"
              className="mb-2 block text-xs text-gray-300"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void f.text().then(setImportText);
              }}
            />
            <textarea aria-label="Client master CSV" className={`${input} h-28 w-full font-mono text-xs`} value={importText} onChange={(e) => setImportText(e.target.value)} placeholder="Client,Industry,Non-profit" />
            <button
              type="button"
              className={`${ghost} mt-2`}
              disabled={busy || parseMasterCsv(importText).length === 0}
              onClick={() => void send('/api/v1/finance/profitability/clients/import', 'PUT', { rows: parseMasterCsv(importText) }).then(() => setImportText(''))}
            >
              Import {parseMasterCsv(importText).length} clients
            </button>
          </section>
          <section>
            <h2 className="mb-2 text-sm font-semibold text-white">Hours a person can work in a month</h2>
            <div className="flex items-center gap-2">
              <input aria-label="Available hours" className={`${input} w-24`} inputMode="decimal" value={hoursPer} onChange={(e) => setHoursPer(e.target.value)} />
              <button type="button" className={ghost} disabled={busy || Number.isNaN(Number(hoursPer)) || Number(hoursPer) <= 0} onClick={() => void send('/api/v1/finance/profitability/settings', 'PUT', { available_hours_per_month: hoursPer })}>
                Save
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
