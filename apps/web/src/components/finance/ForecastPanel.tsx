'use client';

/**
 * Net income > Forecast: for each client with recurring invoices, next invoice run's revenue and margin as the invoices stand today and with every counted line set to the quantity the tools count (the Billing sync
 * differences applied), the lines that would change, and the lines HaloPSA gives no cost (they add revenue but no cost). Every column sorts.
 */
import { useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';

const th = 'px-3 py-2 text-right';
const td = 'px-3 py-1.5 text-right tabular-nums';

export interface ForecastRow {
  client_id: string;
  client_name: string;
  revenue_now: string;
  revenue_forecast: string;
  revenue_change: string;
  cost_now: string;
  cost_forecast: string;
  margin_percent_now: number | null;
  margin_percent_forecast: number | null;
  changed_lines: { item: string; billed: number; counted: number; revenue_change: string }[];
  lines_without_cost: string[];
}
interface Data {
  received_at: string | null;
  forecast: { clients: ForecastRow[]; totals: { revenue_now: string; revenue_forecast: string; revenue_change: string; clients_with_changes: number } } | null;
}

const money = (v: string | number): string => Number(v).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
const pct = (v: number | null): string => (v === null ? 'n/a' : `${v.toFixed(1)}%`);

/** The change in words: "+2 pts" or "-1.5 pts" (pure); empty when either margin is unknown. */
export function pointsChange(a: number | null, b: number | null): string {
  if (a === null || b === null) return '';
  const d = Math.round((b - a) * 10) / 10;
  return d === 0 ? 'no change' : `${d > 0 ? '+' : ''}${d} pts`;
}

export function ForecastPanel() {
  const [data, setData] = useState<Data | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch('/api/v1/finance/forecast');
        if (!res.ok) throw new Error(res.status === 403 ? 'This tab needs both the finance and billing permissions.' : `The API answered ${res.status}`);
        const body = (await res.json()) as Data;
        if (live) setData(body);
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, []);
  const rows = data?.forecast?.clients ?? [];
  const shown = useMemo(() => (sort ? sortedBy(rows, (r) => (r as unknown as Record<string, unknown>)[sort.key] as SortValue, sort.desc) : rows), [rows, sort]);
  if (problem) return <p className="text-sm text-amber-300">{problem}</p>;
  if (!data) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!data.forecast) return <p className="text-sm text-gray-400">HaloPSA has not sent its recurring invoices yet, so there is nothing to forecast.</p>;
  const t = data.forecast.totals;
  return (
    <div className="space-y-3" data-testid="forecast">
      <p className="text-sm text-gray-400">
        Next invoice run per client, as the invoices stand and with every line a tool counts set to the counted quantity. Total revenue {money(t.revenue_now)} now, {money(t.revenue_forecast)} with the counts ({Number(t.revenue_change) >= 0 ? '+' : ''}
        {money(t.revenue_change)}); {t.clients_with_changes} clients have lines that would change. Margin counts only the lines HaloPSA has a cost for.
      </p>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm" data-testid="forecast-table">
          <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
            <tr>
              <SortHeader label="Client" field="client_name" sort={sort} onSort={setSort} text className="px-3 py-2 text-left" />
              <SortHeader label="Revenue now" field="revenue_now" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="Revenue with counts" field="revenue_forecast" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="Change" field="revenue_change" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="Margin now" field="margin_percent_now" sort={sort} onSort={setSort} className={th} />
              <SortHeader label="Margin with counts" field="margin_percent_forecast" sort={sort} onSort={setSort} className={th} />
              <th className="px-3 py-2 text-left">Lines that change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800 text-gray-200">
            {shown.map((r) => (
              <tr key={r.client_id}>
                <td className="px-3 py-1.5 text-left">{r.client_name}</td>
                <td className={td}>{money(r.revenue_now)}</td>
                <td className={td}>{money(r.revenue_forecast)}</td>
                <td className={td}>{Number(r.revenue_change) === 0 ? '' : `${Number(r.revenue_change) > 0 ? '+' : ''}${money(r.revenue_change)}`}</td>
                <td className={td}>{pct(r.margin_percent_now)}</td>
                <td className={td}>
                  {pct(r.margin_percent_forecast)} <span className="text-xs text-gray-500">{pointsChange(r.margin_percent_now, r.margin_percent_forecast)}</span>
                </td>
                <td className="px-3 py-1.5 text-left text-xs text-gray-400">{r.changed_lines.map((c) => `${c.item}: ${c.billed} to ${c.counted}`).join('; ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
