'use client';

/**
 * Net income, the three sections that come from QuickBooks (read only) rather than HaloPSA, after finance's workbook tabs:
 *   P&L                          QuickBooks' profit and loss for a month, line by line as QuickBooks shows it.
 *   QBO Profitability            each client from the revenue QuickBooks booked to net income, with the same cost allocations as the main table.
 *   Historical client revenue    what QuickBooks invoiced each client in every month it holds, with the customers behind each client.
 * Each reads its own data and has its own month list; the figures arrive about once a day.
 */

import { MonthYearPicker } from '@/components/ui/MonthYearPicker';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';
import { money, monthLabel, pct } from './ProfitabilityView';
import type { FullRow } from './NetIncomeView';

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const th = 'px-3 py-2 text-right';
const td = 'px-3 py-1.5 text-right tabular-nums';
// The wide QuickBooks profitability table: smaller cells and whole dollars (the cents are in the cell's tooltip) so all its columns fit across a screen.
const qth = 'px-1.5 py-2 text-right text-[10px] leading-tight';
const qtd = 'px-1.5 py-1.5 text-right tabular-nums text-xs';

/** A whole-dollar amount for a crowded table, with a dash for nothing; the exact amount goes in the title (pure). */
export function moneyWhole(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

/** One JSON read, with the answer, a problem line and a way to ask again. */
function useRead<T>(url: string): { data: T | null; problem: string | null; denied: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const load = useCallback(async () => {
    try {
      const res = await authFetch(url);
      if (res.status === 403) {
        setDenied(true);
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setData((await res.json()) as T);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, [url]);
  useEffect(() => {
    void load();
  }, [load]);
  return { data, problem, denied };
}

function Waiting({ problem, denied, empty }: { problem: string | null; denied: boolean; empty: string | null }) {
  if (denied) return <p className="text-sm text-amber-300">This shows money, so it needs the finance permission.</p>;
  if (problem) return <p className="text-sm text-amber-300">{problem}</p>;
  if (empty) return <p className="text-sm text-gray-400">{empty}</p>;
  return null;
}

const NOT_YET = 'Nothing has arrived from QuickBooks yet. CORE reads it about once a day when QuickBooks is connected.';

/** ---- P&L ---------------------------------------------------------------------------------------------------------------------------------------------------------------- */

export interface PnlLine {
  depth: number;
  kind: 'header' | 'line' | 'total';
  label: string;
  amount: number | null;
}
interface PnlData {
  months: string[];
  month: string | null;
  lines: PnlLine[];
}

/** How a P&L amount reads (pure): an empty cell stays empty, a header has none, a negative one keeps its sign. */
export function pnlAmount(l: PnlLine): string {
  return l.amount === null ? '' : money(l.amount);
}

export function PnlPanel() {
  const [month, setMonth] = useState('');
  const { data, problem, denied } = useRead<PnlData>(`/api/v1/finance/profitability/pnl${month ? `?month=${encodeURIComponent(month)}` : ''}`);
  const waiting = <Waiting problem={problem} denied={denied} empty={data && data.months.length === 0 ? NOT_YET : null} />;
  if (!data || data.months.length === 0) return <div data-testid="pnl-panel">{waiting}</div>;
  return (
    <div className="space-y-3" data-testid="pnl-panel">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-300">
          <span>Month</span>
          <MonthYearPicker name="P&L" months={data.months} value={data.month ?? ''} onChange={setMonth} className={input} />
        </div>
        <p className="text-xs text-gray-500">Live Oak IT Partners, profit and loss, accrual basis, as QuickBooks shows it.</p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm" data-testid="pnl-table">
          <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2 text-left">{data.month ? monthLabel(data.month) : ''}</th>
              <th className={th}>Total</th>
            </tr>
          </thead>
          <tbody className="text-gray-200">
            {data.lines.map((l, i) => (
              <tr key={i} className={l.kind === 'total' ? 'border-t border-gray-700 font-semibold text-white' : l.kind === 'header' ? 'font-medium text-gray-100' : ''}>
                <td className="px-3 py-1 text-left" style={{ paddingLeft: `${12 + l.depth * 20}px` }}>
                  {l.label}
                </td>
                <td className={`${td} ${l.amount !== null && l.amount < 0 ? 'text-red-300' : ''}`}>{pnlAmount(l)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** ---- QBO Profitability ------------------------------------------------------------------------------------------------------------------------------------------------ */

export type QboRow = FullRow & { months_active: number };
interface QboData {
  months: string[];
  report: { month: string; rows: QboRow[]; totals: Record<string, number | null> } | null;
}

/** The workbook's columns worked out from one row (pure): personnel is direct labor plus the true-up, and the margin after personnel is revenue less that. */
export function qboColumns(r: QboRow) {
  // The API sends money as text to keep its cents, so every figure is read as a number before it is added.
  const n = (v: unknown): number => Number(v ?? 0);
  const personnel = n(r.direct_labor) + n(r.labor_trueup);
  return {
    revenue: n(r.revenue),
    cos_personnel: n(r.direct_labor),
    revenue_less_cos_personnel: n(r.revenue) - n(r.direct_labor),
    internal_personnel: n(r.labor_trueup),
    total_personnel: personnel,
    margin_after_personnel: n(r.revenue) - personnel,
    addon_software: n(r.addon_software),
    support_software: n(r.support_software),
    travel: n(r.travel),
    equipment: n(r.equipment),
    hardware: n(r.hardware),
    total_cos: n(r.total_cost),
    gross_profit: n(r.gross_profit),
    gross_margin: r.gross_margin === null || r.gross_margin === undefined ? null : n(r.gross_margin),
    sales_marketing: n(r.sales_marketing),
    overhead: n(r.overhead),
    net_income: n(r.net_income),
    net_margin: r.net_margin === null || r.net_margin === undefined ? null : n(r.net_margin),
    months_active: n(r.months_active),
  };
}
type QboCol = keyof ReturnType<typeof qboColumns>;
export const QBO_HEADERS: [string, QboCol, 'money' | 'pct' | 'int'][] = [
  ['Total revenue', 'revenue', 'money'],
  ['COS personnel', 'cos_personnel', 'money'],
  ['Revenue less COS personnel', 'revenue_less_cos_personnel', 'money'],
  ['Internally coded personnel', 'internal_personnel', 'money'],
  ['Total personnel', 'total_personnel', 'money'],
  ['Margin post personnel', 'margin_after_personnel', 'money'],
  ['Add-on software', 'addon_software', 'money'],
  ['Support software', 'support_software', 'money'],
  ['Travel', 'travel', 'money'],
  ['Equipment', 'equipment', 'money'],
  ['Hardware COGS', 'hardware', 'money'],
  ['Total COS', 'total_cos', 'money'],
  ['Gross profit', 'gross_profit', 'money'],
  ['Gross %', 'gross_margin', 'pct'],
  ['Sales and marketing', 'sales_marketing', 'money'],
  ['Overhead', 'overhead', 'money'],
  ['Net income', 'net_income', 'money'],
  ['Net margin', 'net_margin', 'pct'],
  ['Months active', 'months_active', 'int'],
];

export function QboProfitPanel() {
  const [month, setMonth] = useState('');
  const [sort, setSort] = useState<SortState | null>(null);
  const { data, problem, denied } = useRead<QboData>(`/api/v1/finance/profitability/qbo${month ? `?month=${encodeURIComponent(month)}` : ''}`);
  const rows = useMemo(() => {
    const base = (data?.report?.rows ?? []).map((r) => ({ client_name: r.client_name, ...qboColumns(r) }));
    return sort ? sortedBy(base, (r) => (r as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : base;
  }, [data, sort]);
  if (!data || !data.report) return <div data-testid="qbo-panel"><Waiting problem={problem} denied={denied} empty={data ? NOT_YET : null} /></div>;
  const t = Object.fromEntries(Object.entries(data.report.totals).map(([k, v]) => [k, v === null || v === undefined ? null : Number(v)])) as Record<string, number | null>;
  return (
    <div className="space-y-3" data-testid="qbo-panel">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-300">
          <span>Month</span>
          <MonthYearPicker name="QBO" months={data.months} value={data.report.month} onChange={setMonth} className={input} />
        </div>
        <p className="text-xs text-gray-500">Revenue is what QuickBooks booked for the client (sales by customer); hours, labor and the cost allocations are the same as on Revenue to net income. Commissions are not a client.</p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm" data-testid="qbo-table">
          <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
            <tr>
              <SortHeader label="Client" field="client_name" sort={sort} onSort={setSort} text className="px-2 py-2 text-left text-[10px]" />
              {QBO_HEADERS.map(([h, f]) => (
                <SortHeader key={f} label={h} field={f} sort={sort} onSort={setSort} className={qth} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800 text-gray-200">
            {rows.map((r) => (
              <tr key={r.client_name}>
                <td className="px-2 py-1.5 text-left text-xs">{r.client_name}</td>
                {QBO_HEADERS.map(([, f, kind]) => (
                  <td key={f} className={`${qtd} ${f === 'net_income' && (r[f] as number) < 0 ? 'text-red-300' : ''}`} title={kind === 'money' ? money(r[f] as number) : undefined}>
                    {kind === 'money' ? moneyWhole(r[f] as number) : kind === 'pct' ? pct(r[f] as number | null) : String(r[f])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-gray-700 text-gray-100">
            <tr>
              <td className="px-2 py-2 text-left text-xs font-medium">Total</td>
              {QBO_HEADERS.map(([, f, kind]) => {
                const total: Record<string, number | null> = {
                  revenue: t.revenue ?? 0,
                  cos_personnel: t.direct_labor ?? 0,
                  revenue_less_cos_personnel: (t.revenue ?? 0) - (t.direct_labor ?? 0),
                  internal_personnel: t.labor_trueup ?? 0,
                  total_personnel: (t.direct_labor ?? 0) + (t.labor_trueup ?? 0),
                  margin_after_personnel: (t.revenue ?? 0) - (t.direct_labor ?? 0) - (t.labor_trueup ?? 0),
                  addon_software: t.addon_software ?? 0,
                  support_software: t.support_software ?? 0,
                  travel: t.travel ?? 0,
                  equipment: t.equipment ?? 0,
                  hardware: t.hardware ?? 0,
                  total_cos: t.total_cost ?? 0,
                  gross_profit: t.gross_profit ?? 0,
                  gross_margin: t.gross_margin ?? null,
                  sales_marketing: t.sales_marketing ?? 0,
                  overhead: t.overhead ?? 0,
                  net_income: t.net_income ?? 0,
                  net_margin: t.net_margin ?? null,
                };
                return (
                  <td key={f} className={qtd} title={kind === 'money' ? money(total[f] ?? 0) : undefined}>
                    {f === 'months_active' ? '' : kind === 'pct' ? pct(total[f] ?? null) : moneyWhole(total[f] ?? 0)}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

/** ---- Historical client revenue ---------------------------------------------------------------------------------------------------------------------------------------- */

interface HistoryClient {
  client: string;
  total: number;
  by_month: Record<string, number>;
  qbo_names: string[];
}
interface HistoryData {
  months: string[];
  clients: HistoryClient[];
}

/** The clients that match what was typed (pure): the client or any QuickBooks customer behind it, in any case. */
export function filterClients(clients: HistoryClient[], text: string): HistoryClient[] {
  const needle = text.trim().toLowerCase();
  if (!needle) return clients;
  return clients.filter((c) => c.client.toLowerCase().includes(needle) || c.qbo_names.some((n) => n.toLowerCase().includes(needle)));
}

export function HistoryPanel() {
  const { data, problem, denied } = useRead<HistoryData>('/api/v1/finance/profitability/qbo-history');
  const [sort, setSort] = useState<SortState | null>(null);
  const [text, setText] = useState('');
  const rows = useMemo(() => {
    const base = filterClients(data?.clients ?? [], text).map((c) => ({ ...c, ...Object.fromEntries(Object.entries(c.by_month).map(([m, v]) => [`m_${m}`, v])) }));
    return sort ? sortedBy(base, (r) => (r as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : base;
  }, [data, sort, text]);
  if (!data || data.months.length === 0) return <div data-testid="history-panel"><Waiting problem={problem} denied={denied} empty={data ? NOT_YET : null} /></div>;
  const monthTotal = (m: string) => rows.reduce((n, r) => n + Number(r.by_month[m] ?? 0), 0);
  return (
    <div className="space-y-3" data-testid="history-panel">
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Find a client" placeholder="Find a client or a QuickBooks customer" value={text} onChange={(e) => setText(e.target.value)} className={`${input} w-72`} />
        <p className="text-xs text-gray-500">What QuickBooks invoiced each client each month, accrual. A customer is counted under the client it is grouped with (Settings &gt; Finance &gt; Client groups); hover a client to see the customers behind it.</p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm" data-testid="history-table">
          <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
            <tr>
              <SortHeader label="Client" field="client" sort={sort} onSort={setSort} text className="sticky left-0 bg-gray-900 px-3 py-2 text-left" />
              {data.months.map((m) => (
                <SortHeader key={m} label={monthLabel(m)} field={`m_${m}`} sort={sort} onSort={setSort} className={th} />
              ))}
              <SortHeader label="Total" field="total" sort={sort} onSort={setSort} className={th} />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800 text-gray-200">
            {rows.map((r) => (
              <tr key={r.client}>
                <td className="sticky left-0 bg-gray-950 px-3 py-1.5 text-left" title={r.qbo_names.join(', ')}>
                  {r.client}
                </td>
                {data.months.map((m) => (
                  <td key={m} className={td}>
                    {r.by_month[m] === undefined ? '' : money(r.by_month[m])}
                  </td>
                ))}
                <td className={`${td} font-medium text-white`}>{money(r.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-gray-700 text-gray-100">
            <tr>
              <td className="sticky left-0 bg-gray-950 px-3 py-2 text-left font-medium">Total</td>
              {data.months.map((m) => (
                <td key={m} className={td}>
                  {money(monthTotal(m))}
                </td>
              ))}
              <td className={`${td} font-semibold`}>{money(rows.reduce((n, r) => n + Number(r.total), 0))}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
