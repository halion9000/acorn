'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import useSWR from 'swr';
import { alertsApi, tenantsApi } from '@/lib/api';

/**
 * Give this one alert to a person, or take it off whoever has it. It uses the same assign request as the list's bulk bar (so the same audit entry is kept), with this one alert. Shows nothing to someone who cannot
 * list people.
 */
export function AssignAlert({ alertId, onDone }: { alertId: string; onDone: () => void }) {
  const { data: people } = useSWR('assign-people', () => tenantsApi.users().catch(() => null), { revalidateOnFocus: false });
  const [who, setWho] = useState('');
  const [busy, setBusy] = useState(false);
  if (!people) return null;
  const active = people.filter((p) => p.is_active);

  const submit = async () => {
    if (!who) return;
    setBusy(true);
    try {
      const r = await alertsApi.bulkAssign({ alert_ids: [alertId], assignee_id: who === 'none' ? null : who });
      toast.success(r.assignee_name ? `Assigned to ${r.assignee_name}.` : 'Unassigned.');
      setWho('');
      onDone();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not assign the alert.');
    } finally {
      setBusy(false);
    }
  };

  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs';
  return (
    <span className="ml-2 inline-flex items-center gap-1" data-testid="assign-alert">
      <select aria-label="Assign this alert to" value={who} onChange={(e) => setWho(e.target.value)} className={field}>
        <option value="">Assign to…</option>
        <option value="none">Nobody (unassign)</option>
        {active.map((p) => (
          <option key={p.id} value={p.id}>
            {p.email ?? p.account_name}
          </option>
        ))}
      </select>
      <button type="button" disabled={busy || !who} onClick={() => void submit()} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
        {busy ? 'Saving…' : 'Assign'}
      </button>
    </span>
  );
}
