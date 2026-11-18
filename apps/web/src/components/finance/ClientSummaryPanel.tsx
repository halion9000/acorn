'use client';

/**
 * Net income > Client summary, after finance's workbook tab "Summary": every client across the last twelve months to a chosen month, with its industry, whether it is for profit, the months it has had revenue,
 * the year to date (revenue, net income, average net margin and the band that margin falls in) and each month's net income. Every column sorts; the industry and the for-profit choice narrow the list.
 */

import { useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';
import { money, monthLabel, pct } from './ProfitabilityView';

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const th = 'px-3 py-2 text-right';
const td = 'px-3 py-1.5 text-right tabular-nums';

export interface SummaryRow {
  client_key: string;
  client_name: string;
  industry: string;
  for_profit: boolean;
  months_active: number;
  ytd_revenue: number | string;
  ytd_net_income: number | string;
  ytd_net_margin: number | null;
  bracket: string;
  by_month: Record<string, { revenue: number | string; net_income: number | string; net_margin: number | null }>;
}
interface SummaryData {
  received_at: string | null;
  available?: string[];
  months: string[];
  through: string | null;
  rows: SummaryRow[];
}

/** The rows that match the chosen industry and for-profit choice and the typed text (pure). */
export function filterSummary(rows: SummaryRow[], industry: string, profit: 'all' | 'for' | 'non', text: string): SummaryRow[] {
  const needle = text.trim().toLowerCase();
  return rows.filter(
    (r) => (industry === 'all' || (r.industry || 'No industry') === industry) && (profit === 'all' || (profit === 'for') === r.for_profit) && (!needle || r.client_name.toLowerCase().includes(needle)),
  );
}

export function ClientSummaryPanel() {
  const [month, setMonth] = useState('');
  const [data, setData] = useState<SummaryData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [sort, setSort] = useState<SortState | null>(null);
  const [industry, setIndustry] = useState('all');
  const [profit, setProfit] = useState<'all' | 'for' | 'non'>('all');
  const [text, setText] = useState('');

  useEffect(() => {
    let live = true;
    setProblem(null);
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/finance/profitability/summary${month ? `?month=${encodeURIComponent(month)}` : ''}`);
        if (res.status === 403) {
          if (live) setDenied(true);
          return;
        }
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        if (live) setData((await res.json()) as SummaryData);
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, [month]);

  const industries = useMemo(() => [...new Set((data?.rows ?? []).map((r) => r.industry || 'No industry'))].sort((a, b) => a.localeCompare(b)), [data]);
  const rows = useMemo(() => {
    const base = filterSummary(data?.rows ?? [], industry, profit, text).map((r) => ({
      ...r,
      for_profit_text: r.for_profit ? 'For-profit' : 'Non-profit',
      ...Object.fromEntries(Object.entries(r.by_month).map(([m, v]) => [`m_${m}`, v.net_income])),
    }));
    return sort ? sortedBy(base, (r) => (r as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : base;
  }, [data, industry, profit, text, sort]);

  if (denied) return <p className="text-sm text-amber-300">This shows money, so it needs the finance permission.</p>;
  if (problem) return <p className="text-sm text-amber-300">{problem}</p>;
  if (!data) return null;
  if (data.rows.length === 0) return <p className="text-sm text-gray-400" data-testid="summary-panel">Nothing has arrived from HaloPSA yet, so there is nothing to summarize.</p>;
  return (
    <div className="space-y-3" data-testid="summary-panel">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Through
          <select aria-label="Summary month" className={input} value={data.through ?? ''} onChange={(e) => setMonth(e.target.value)}>
            {[...(data.available ?? [])].reverse().map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
        </label>
        <select aria-label="Industry" className={input} value={industry} onChange={(e) => setIndustry(e.target.value)}>
          <option value="all">All industries</option>
          {industries.map((i) => (
            <option key={i} value={i}>
              {i}
            </option>
          ))}
        </select>
        <select aria-label="For-profit or non-profit" className={input} value={profit} onChange={(e) => setProfit(e.target.value as 'all' | 'for' | 'non')}>
          <option value="all">For-profit and non-profit</option>
          <option value="for">For-profit</option>
          <option value="non">Non-profit</option>
        </select>
        <input aria-label="Find a client" placeholder="Find a client" className={`${input} w-56`} value={text} onChange={(e) => setText(e.target.value)} />
        <p className="text-xs text-gray-500">The year to date is the months of {data.through ? data.through.slice(0, 4) : 'the year'} up to the month chosen; each month column is that month&apos;s net income.</p>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm" data-testid="summary-table">
          <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
            <tr>
              <SortHeader label="Client" field="client_name" sort={sort} onSort={setSort} text className="sticky left-0 bg-gray-900 px-3 py-2 text-left" />
              <SortHeader label="Industry" field="industry" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
              <SortHeader label="For profit?" field="for_profit_text" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
              <SortHeader label="Months active" field="months_active" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="YTD revenue" field="ytd_revenue" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="YTD net income" field="ytd_net_income" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="YTD net %" field="ytd_net_margin" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="Margin band" field="bracket" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
              {data.months.map((m) => (
                <SortHeader key={m} label={monthLabel(m)} field={`m_${m}`} sort={sort} onSort={setSort} className={th} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800 text-gray-200">
            {rows.map((r) => (
              <tr key={r.client_key}>
                <td className="sticky left-0 bg-gray-950 px-3 py-1.5 text-left">{r.client_name}</td>
                <td className="px-3 py-1.5 text-left">{r.industry || '—'}</td>
                <td className="px-3 py-1.5 text-left">{r.for_profit_text}</td>
                <td className={td}>{r.months_active}</td>
                <td className={td}>{money(Number(r.ytd_revenue))}</td>
                <td className={`${td} ${Number(r.ytd_net_income) < 0 ? 'text-red-300' : ''}`}>{money(Number(r.ytd_net_income))}</td>
                <td className={td}>{pct(r.ytd_net_margin)}</td>
                <td className="px-3 py-1.5 text-left">{r.bracket}</td>
                {data.months.map((m) => (
                  <td key={m} className={`${td} ${r.by_month[m] && Number(r.by_month[m]!.net_income) < 0 ? 'text-red-300' : ''}`}>
                    {r.by_month[m] ? money(Number(r.by_month[m]!.net_income)) : ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-gray-700 text-gray-100">
            <tr>
              <td className="sticky left-0 bg-gray-950 px-3 py-2 text-left font-medium">Total ({rows.length})</td>
              <td />
              <td />
              <td />
              <td className={td}>{money(rows.reduce((n, r) => n + Number(r.ytd_revenue), 0))}</td>
              <td className={td}>{money(rows.reduce((n, r) => n + Number(r.ytd_net_income), 0))}</td>
              <td />
              <td />
              {data.months.map((m) => (
                <td key={m} className={td}>
                  {money(rows.reduce((n, r) => n + Number(r.by_month[m]?.net_income ?? 0), 0))}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
