'use client';

/**
 * Monthly Licensing, the Rewst way: which apps each client is billed for in a month, from the invoice lines. A month picker (the last twelve months), a software filter (the apps billed to three or more clients are
 * ticked to start with), a clients filter, and a table of clients against apps with a check or a dash, the percentage of the common apps the client has, and how many of the apps shown it has.
 */
import { useState } from 'react';

import { MetricPicker } from './MetricPicker';
import { NothingYet, Panel, monthShort, selectClass, useMetric } from './kit';

export interface AppsData {
  received_at: string | null;
  months: string[];
  month: string | null;
  apps: { app: string; clients: number; common: boolean }[];
  clients: { client: string; apps: string[] }[];
}

/** The share of the common apps a client is billed for, as a whole percent (pure); 0 when there are none. */
export function appPercent(have: string[], common: string[]): number {
  if (common.length === 0) return 0;
  const set = new Set(have);
  return Math.round((common.filter((a) => set.has(a)).length / common.length) * 100);
}

export function LicensingApps() {
  const [month, setMonth] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null); // null: the common apps
  const [hiddenClients, setHiddenClients] = useState<Set<string>>(new Set());
  const { data } = useMetric<AppsData>(`/api/v1/reports/metrics/licensing-apps${month ? `?month=${month}` : ''}`);
  if (!data || !Array.isArray(data.apps) || !Array.isArray(data.clients)) return null;
  if (!data.received_at) return <NothingYet show what="the invoice lines" />;
  const common = data.apps.filter((a) => a.common).map((a) => a.app);
  const selected = picked ?? common;
  const shown = data.apps.filter((a) => selected.includes(a.app)).map((a) => a.app);
  const clients = data.clients.filter((c) => !hiddenClients.has(c.client));
  const allClients = data.clients.map((c) => c.client);
  return (
    <div className="space-y-4" data-testid="licensing-apps">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          Billed month
          <select aria-label="Billed month" className={selectClass} value={data.month ?? ''} onChange={(e) => setMonth(e.target.value)}>
            {data.months.map((m) => (
              <option key={m} value={m}>
                {monthShort(m)}
              </option>
            ))}
          </select>
        </label>
        <MetricPicker noun="software" options={data.apps.map((a) => ({ value: a.app, label: a.app, hint: String(a.clients) }))} selected={selected} onChange={(next) => setPicked(next)} />
        <MetricPicker noun="clients" options={allClients.map((c) => ({ value: c, label: c }))} selected={allClients.filter((c) => !hiddenClients.has(c))} onChange={(next) => setHiddenClients(new Set(allClients.filter((c) => !next.includes(c))))} />
      </div>
      <Panel title="Apps billed per client" testId="licensing-apps-table">
        <div className="max-h-[36rem] overflow-auto">
          <table className="w-full min-w-max border-collapse text-sm">
            <thead className="sticky top-0 z-10" style={{ background: '#1f2f33' }}>
              <tr>
                <th className="sticky left-0 px-4 py-2 text-left font-semibold" style={{ background: '#1f2f33' }}>
                  Client Name
                </th>
                <th className="px-3 py-2 text-center font-semibold">Percentage</th>
                {shown.map((a) => (
                  <th key={a} className="px-3 py-2 text-center font-semibold">
                    {a}
                  </th>
                ))}
                <th className="px-3 py-2 text-center font-semibold">Total Apps</th>
              </tr>
            </thead>
            <tbody>
              {clients.length === 0 ? (
                <tr>
                  <td colSpan={shown.length + 3} className="px-4 py-3 text-center text-gray-400">
                    No clients selected
                  </td>
                </tr>
              ) : (
                clients.map((c) => (
                  <tr key={c.client} className="border-t border-gray-800">
                    <td className="sticky left-0 whitespace-nowrap px-4 py-1.5 font-medium" style={{ background: '#243236' }}>
                      {c.client}
                    </td>
                    <td className="px-3 py-1.5 text-center font-semibold tabular-nums" style={{ color: '#5dd6ff' }}>
                      {appPercent(c.apps, common)}%
                    </td>
                    {shown.map((a) => (
                      <td key={a} className="px-3 py-1.5 text-center">
                        {c.apps.includes(a) ? '✓' : '–'}
                      </td>
                    ))}
                    <td className="px-3 py-1.5 text-center tabular-nums">{shown.filter((a) => c.apps.includes(a)).length}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
