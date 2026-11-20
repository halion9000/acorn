'use client';

/**
 * The Profitability trend (the Rewst page's charts): revenue against labor by month, what is left after labor by month, how many clients were invoiced each month and every client month by month. Same pricing as
 * the month view; read from the summary CORE sends once a day.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { AreaChart } from '@/components/metrics/AreaChart';
import { Columns, PairedColumns, Panel, Table, monthShort } from '@/components/metrics/kit';

type Amount = number | string;
export interface TrendData {
  received_at: string | null;
  months: string[];
  available_months?: number;
  series: { month: string; revenue: Amount; labor: Amount; after_labor: Amount; margin_percent: number | null; hours: Amount; clients_invoiced: number }[];
  clients: { client_id: string; client_name: string; revenue: Amount; by_month: Record<string, { revenue: Amount; labor: Amount; after_labor: Amount }> }[];
  clients_left_out?: number;
}

export const whole = (n: Amount): number => Math.round(Number(n) || 0);
const dollars = (n: Amount): string => whole(n).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

/** Each client's row for the breakdown table: the profit (after labor) in each month, with the total and the margin over the whole period (pure). */
export function breakdownRow(c: TrendData['clients'][number], months: string[]): string[] {
  const revenue = months.reduce((a, m) => a + Number(c.by_month[m]?.revenue ?? 0), 0);
  const profit = months.reduce((a, m) => a + Number(c.by_month[m]?.after_labor ?? 0), 0);
  return [c.client_name, ...months.map((m) => (c.by_month[m] ? dollars(c.by_month[m]!.after_labor) : '—')), dollars(profit), revenue > 0 ? `${((profit / revenue) * 100).toFixed(1)}%` : '—'];
}

export function ProfitTrend({ months = 12 }: { months?: number }) {
  const [data, setData] = useState<TrendData | null>(null);
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch(`/api/v1/finance/profitability/trend?months=${months}`);
        if (res.ok && live) setData((await res.json()) as TrendData);
      } catch {
        /* the month view above still works without the trend */
      }
    })();
    return () => {
      live = false;
    };
  }, [months]);
  if (!data?.received_at || !Array.isArray(data.series) || data.series.length === 0) return null;
  const labels = data.series.map((s) => monthShort(s.month));
  return (
    <div className="space-y-4" data-testid="profit-trend">
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Revenue vs labor by month" testId="trend-revenue-labor">
          <PairedColumns points={data.series.map((s, i) => ({ label: labels[i]!, a: whole(s.revenue), b: whole(s.labor) }))} aLabel="Revenue" bLabel="Labor" />
        </Panel>
        <Panel title="Left after labor by month" testId="trend-after-labor">
          <AreaChart points={data.series.map((s, i) => ({ label: labels[i]!, value: Math.max(0, whole(s.after_labor)) }))} color="#66bb6a" testId="trend-after-labor-chart" />
        </Panel>
        <Panel title="Clients invoiced per month" testId="trend-clients">
          <Columns points={data.series.map((s, i) => ({ label: labels[i]!, value: s.clients_invoiced }))} />
        </Panel>
      </div>
      <Panel title="Monthly breakdown by client: left after labor" testId="trend-breakdown">
        <Table head={['Client', ...labels, 'Total', 'Margin']} rows={data.clients.map((c) => breakdownRow(c, data.months))} />
        {data.clients_left_out ? <p className="mt-2 text-xs text-gray-500">The {data.clients_left_out} smallest clients are not shown.</p> : null}
      </Panel>
    </div>
  );
}
