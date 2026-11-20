'use client';

/**
 * The HaloPSA user roles (the Rewst User Roles page): how many users each client has in each role (Accountants, C-Suite, Computer User, Primary POC...), with a roles filter, a clients filter, a Total for each
 * client and the non-zero counts picked out. CORE reads them from HaloPSA about once a day.
 */
import { useState } from 'react';

import { MetricPicker } from './MetricPicker';
import { NothingYet, Panel, num, useMetric } from './kit';

export interface HaloRolesData {
  received_at: string | null;
  roles: { role: string; total: number }[];
  clients: { client: string; client_id: string; counts: Record<string, number>; total: number }[];
  all_clients: string[];
  without_client: number;
  unread: string[];
}

/** The total a client shows for the roles that are ticked (pure): not the client's whole total, so the column follows the filter. */
export const shownTotal = (counts: Record<string, number>, roles: string[]): number => roles.reduce((sum, r) => sum + (counts[r] ?? 0), 0);

export function HaloUserRolesPanel() {
  const { data } = useMetric<HaloRolesData>('/api/v1/reports/metrics/halo-user-roles');
  const [hiddenRoles, setHiddenRoles] = useState<Set<string>>(new Set());
  const [hiddenClients, setHiddenClients] = useState<Set<string>>(new Set());
  if (!data || !Array.isArray(data.roles) || !Array.isArray(data.clients) || !Array.isArray(data.all_clients)) return null;
  if (!data.received_at) return <NothingYet show what="the HaloPSA user roles" />;
  const roles = data.roles.map((r) => r.role).filter((r) => !hiddenRoles.has(r));
  const clients = data.clients.filter((c) => !hiddenClients.has(c.client));
  return (
    <div className="space-y-4" data-testid="halo-roles">
      <div className="flex flex-wrap gap-3">
        <MetricPicker
          noun="roles"
          options={data.roles.map((r) => ({ value: r.role, label: r.role, hint: String(r.total) }))}
          selected={roles}
          onChange={(next) => setHiddenRoles(new Set(data.roles.map((r) => r.role).filter((k) => !next.includes(k))))}
        />
        <MetricPicker
          noun="clients"
          options={data.all_clients.map((c) => ({ value: c, label: c }))}
          selected={data.all_clients.filter((c) => !hiddenClients.has(c))}
          onChange={(next) => setHiddenClients(new Set(data.all_clients.filter((k) => !next.includes(k))))}
        />
      </div>
      <Panel title="Users by role and client" testId="halo-roles-table">
        <div className="max-h-[36rem] overflow-auto">
          <table className="w-full min-w-max border-collapse text-sm">
            <thead className="sticky top-0 z-10" style={{ background: '#1f2f33' }}>
              <tr>
                <th className="sticky left-0 px-4 py-2 text-left font-semibold" style={{ background: '#1f2f33' }}>
                  Client Name
                </th>
                {roles.map((r) => (
                  <th key={r} className="px-3 py-2 text-center font-semibold">
                    {r}
                  </th>
                ))}
                <th className="px-3 py-2 text-center font-semibold">Total</th>
              </tr>
            </thead>
            <tbody>
              {clients.length === 0 ? (
                <tr>
                  <td colSpan={roles.length + 2} className="px-4 py-3 text-center text-gray-400">
                    No clients selected
                  </td>
                </tr>
              ) : (
                clients.map((c) => (
                  <tr key={c.client} className="border-t border-gray-800">
                    <td className="sticky left-0 whitespace-nowrap px-4 py-1.5 font-medium" style={{ background: '#243236' }}>
                      {c.client}
                    </td>
                    {roles.map((r) => (
                      <td key={r} data-has-value={(c.counts[r] ?? 0) > 0} className="px-3 py-1.5 text-center tabular-nums" style={(c.counts[r] ?? 0) > 0 ? { background: 'rgba(0,212,255,0.14)', fontWeight: 600 } : { color: 'var(--metrics-soft)' }}>
                        {num(c.counts[r] ?? 0)}
                      </td>
                    ))}
                    <td className="px-3 py-1.5 text-center font-semibold tabular-nums" style={{ background: 'rgba(0,212,255,0.14)' }}>
                      {num(shownTotal(c.counts, roles))}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {data.unread.length > 0 ? <p className="mt-2 text-xs text-amber-300">These roles could not be read from HaloPSA and are left out: {data.unread.join(', ')}.</p> : null}
        {data.without_client > 0 ? <p className="mt-1 text-xs text-gray-500">{data.without_client} users have no client and are not counted.</p> : null}
      </Panel>
    </div>
  );
}
