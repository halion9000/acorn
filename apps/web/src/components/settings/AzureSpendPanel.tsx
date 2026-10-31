'use client';

import { useState } from 'react';
import useSWR from 'swr';

import { Skeleton } from '@/components/ui/Skeleton';
import { useTenant } from '@/components/layout/TenantProvider';
import { azureSpendApi, type AzureSpend } from '@/lib/api';
import { PanelHeader, errorText } from './panel-parts';

const TITLE = 'Azure spend';
const DESCRIPTION = 'What the Azure resources that run A.C.O.R.N cost this month. Azure posts charges with a delay, so the newest day is often missing.';

export function money(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** Month-to-date cost, a month-end projection, spend by service and by day (server: platform_azure_spend.py). No budget is assumed: a bar appears only when one is set on the server. */
export function AzureSpendPanel() {
  const { viewingOther, home } = useTenant();
  if (viewingOther) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p data-testid="viewing-other-notice" className="px-6 py-5 text-sm text-amber-200">
          This is a platform setting. Return to {home?.name ?? 'your tenant'} (the banner above has the button) and open this page again.
        </p>
      </div>
    );
  }
  return <Inner />;
}

function Tile({ label, value, hint, testId }: { label: string; value: string; hint?: string; testId: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div data-testid={testId} className="mt-1 text-2xl font-semibold text-gray-100">{value}</div>
      {hint ? <div className="mt-1 text-xs text-gray-500">{hint}</div> : null}
    </div>
  );
}

function Inner() {
  const { data, error: loadError, isLoading, mutate } = useSWR('settings:azure-spend', () => azureSpendApi.get());
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await mutate(await azureSpendApi.get(true), { revalidate: false });
    } finally {
      setRefreshing(false);
    }
  };

  if (isLoading && !data) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <div className="px-6 py-5"><Skeleton className="h-32 w-full rounded-lg" /></div>
      </div>
    );
  }
  if (!data) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p role="alert" className="px-6 py-5 text-sm text-red-300">{errorText(loadError, 'The Azure spend could not be loaded.')}</p>
      </div>
    );
  }
  if (!data.configured) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p data-testid="spend-unconfigured" className="px-6 py-5 text-sm text-gray-400">
          Not set up on this A.C.O.R.N. It reads Azure&apos;s costs with the server&apos;s own Azure identity, so it is available where A.C.O.R.N runs on an Azure server with ACORN_AZURE_SPEND_SCOPE set.
        </p>
      </div>
    );
  }
  const maxDay = Math.max(0, ...data.daily.map((d) => d.cost));
  const budgetShare = data.budget ? Math.min(100, (data.total / data.budget) * 100) : null;
  return (
    <div>
      <PanelHeader
        title={TITLE}
        description={DESCRIPTION}
        action={
          <button type="button" disabled={refreshing} onClick={() => void refresh()} className="rounded-lg border border-gray-700 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800 disabled:opacity-50">
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        }
      />
      <div className="space-y-6 px-6 py-5">
        {data.error ? (
          <p role="alert" data-testid="spend-error" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
            {data.error}
            {data.stale ? ' Showing the last answer.' : ''}
          </p>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-3">
          <Tile testId="spend-total" label={`So far in ${data.month || 'this month'}`} value={money(data.total, data.currency)} />
          <Tile testId="spend-forecast" label="Projected for the month" value={data.forecast === null ? 'Not enough data yet' : money(data.forecast, data.currency)} hint="Average of the days with charges, over the whole month." />
          {data.budget ? <Tile testId="spend-budget" label="Budget" value={money(data.budget, data.currency)} hint={`${Math.round(budgetShare ?? 0)}% used so far`} /> : null}
        </div>
        {budgetShare !== null ? (
          <div role="progressbar" aria-label="Budget used" aria-valuenow={Math.round(budgetShare)} aria-valuemin={0} aria-valuemax={100} className="h-2 overflow-hidden rounded bg-gray-800">
            <div className="h-full bg-blue-500" style={{ width: `${budgetShare}%` }} />
          </div>
        ) : null}
        <section aria-label="By service">
          <h3 className="mb-2 text-sm font-medium text-gray-300">By service</h3>
          {data.by_service.length === 0 ? (
            <p data-testid="spend-empty" className="text-sm text-gray-500">Azure has not posted any charges for this month yet.</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {data.by_service.map((row) => (
                  <tr key={row.service} className="border-b border-gray-800/60">
                    <td className="py-1.5 text-gray-300">{row.service}</td>
                    <td className="py-1.5 text-right tabular-nums text-gray-200">{money(row.cost, data.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        {data.daily.length > 0 ? (
          <section aria-label="By day">
            <h3 className="mb-2 text-sm font-medium text-gray-300">By day</h3>
            <div className="flex h-24 items-end gap-1">
              {data.daily.map((d) => (
                <div key={d.date} title={`${d.date}: ${money(d.cost, data.currency)}`} data-testid="spend-day" className="flex-1 rounded-t bg-blue-500/70" style={{ height: `${maxDay > 0 ? Math.max(2, (d.cost / maxDay) * 100) : 2}%` }} />
              ))}
            </div>
          </section>
        ) : null}
        {data.fetched_at ? <p className="text-xs text-gray-500" suppressHydrationWarning>Read from Azure {new Date(data.fetched_at).toLocaleString()}. Azure limits how often this can be refreshed.</p> : null}
      </div>
    </div>
  );
}
