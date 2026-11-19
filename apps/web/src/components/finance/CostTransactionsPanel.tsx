'use client';

/**
 * Net income > QBO Travel and Hardware COGS, after finance's workbook tabs of the same names: the transactions QuickBooks booked to the travel accounts (5800, 5805) or the hardware account (5600) in a month, each with the client its
 * customer is counted under, who was paid, the memo and the amount, and the total for each client. Every column sorts and a month can be chosen.
 */

import { MonthYearPicker } from '@/components/ui/MonthYearPicker';
import { useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';
import { money, monthLabel } from './ProfitabilityView';

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const td = 'px-3 py-1.5 text-right tabular-nums';

export interface CostTx {
  account: string;
  date: string;
  type: string;
  name: string;
  customer: string;
  client: string;
  memo: string;
  split: string;
  amount: number | string;
}
interface TxData {
  months: string[];
  month: string | null;
  kind: 'travel' | 'hardware';
  rows: CostTx[];
  by_client: { client: string; total: number | string }[];
  total: number | string;
}

/** The transactions whose client, customer, vendor or memo contain what was typed, in any case (pure). */
export function filterTransactions(rows: CostTx[], text: string): CostTx[] {
  const needle = text.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((r) => `${r.client} ${r.customer} ${r.name} ${r.memo}`.toLowerCase().includes(needle));
}

export function CostTransactionsPanel({ kind }: { kind: 'travel' | 'hardware' }) {
  const [month, setMonth] = useState('');
  const [data, setData] = useState<TxData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [sort, setSort] = useState<SortState | null>(null);
  const [text, setText] = useState('');

  useEffect(() => {
    let live = true;
    setProblem(null);
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/finance/profitability/transactions?kind=${kind}${month ? `&month=${encodeURIComponent(month)}` : ''}`);
        if (res.status === 403) {
          if (live) setDenied(true);
          return;
        }
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        if (live) setData((await res.json()) as TxData);
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, [kind, month]);

  const rows = useMemo(() => {
    const base = filterTransactions(data?.rows ?? [], text);
    return sort ? sortedBy(base, (r) => (r as unknown as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : base;
  }, [data, text, sort]);

  const label = kind === 'travel' ? 'travel' : 'hardware';
  if (denied) return <p className="text-sm text-amber-300">This shows money, so it needs the finance permission.</p>;
  if (problem) return <p className="text-sm text-amber-300">{problem}</p>;
  if (!data) return null;
  if (data.months.length === 0) return <p className="text-sm text-gray-400" data-testid="tx-panel">Nothing has arrived from QuickBooks yet. CORE reads it about once a day when QuickBooks is connected.</p>;
  return (
    <div className="space-y-3" data-testid="tx-panel">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-300">
          <span>Month</span>
          <MonthYearPicker name="Transactions" months={data.months} value={data.month ?? ''} onChange={setMonth} className={input} />
        </div>
        <input aria-label="Find a transaction" placeholder="Find a client, vendor or memo" className={`${input} w-64`} value={text} onChange={(e) => setText(e.target.value)} />
        <p className="text-xs text-gray-500">{kind === 'travel' ? 'Accounts 5800 and 5805' : 'Account 5600'}, as QuickBooks booked them. A customer is counted under the client it is grouped with (Settings &gt; Finance &gt; Client groups).</p>
      </div>
      {data.rows.length === 0 ? (
        <p className="text-sm text-gray-400" data-testid="tx-empty">No {label} transactions in {data.month ? monthLabel(data.month) : 'this month'}.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm" data-testid="tx-table">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <SortHeader label="Date" field="date" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Client" field="client" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Customer" field="customer" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Paid to" field="name" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Memo" field="memo" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Paid from" field="split" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
                  <SortHeader label="Amount" field="amount" sort={sort} onSort={setSort} className="px-3 py-2 text-right" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {rows.map((r, i) => (
                  <tr key={`${r.date}-${r.name}-${i}`}>
                    <td className="px-3 py-1.5 text-left">{r.date}</td>
                    <td className="px-3 py-1.5 text-left">{r.client || '—'}</td>
                    <td className="px-3 py-1.5 text-left">{r.customer || '—'}</td>
                    <td className="px-3 py-1.5 text-left">{r.name}</td>
                    <td className="px-3 py-1.5 text-left">{r.memo}</td>
                    <td className="px-3 py-1.5 text-left">{r.split}</td>
                    <td className={td}>{money(Number(r.amount))}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-gray-700 text-gray-100">
                <tr>
                  <td className="px-3 py-2 text-left font-medium" colSpan={6}>
                    Total ({rows.length})
                  </td>
                  <td className={`${td} font-semibold`}>{money(rows.reduce((n, r) => n + Number(r.amount), 0))}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="overflow-x-auto rounded-lg border border-gray-800 self-start">
            <table className="w-full text-sm" data-testid="tx-by-client">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left">Client</th>
                  <th className="px-3 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 text-gray-200">
                {data.by_client.map((c) => (
                  <tr key={c.client}>
                    <td className="px-3 py-1.5 text-left">{c.client}</td>
                    <td className={td}>{money(Number(c.total))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
