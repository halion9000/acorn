'use client';

import { useState } from 'react';
import toast from 'react-hot-toast';
import useSWR from 'swr';
import { alertsApi, tenantsApi, type BulkAssignResult } from '@/lib/api';

/** "Assigned 3 alerts to amy@acme.com. 1 was already finished." / "Unassigned 3 alerts." */
export function assignSummary(r: BulkAssignResult): string {
  const noun = (n: number) => `${n} alert${n === 1 ? '' : 's'}`;
  const parts = [r.assignee_name ? `Assigned ${noun(r.assigned)} to ${r.assignee_name}.` : `Unassigned ${noun(r.assigned)}.`];
  if (r.already_finished > 0) parts.push(`${r.already_finished} ${r.already_finished === 1 ? 'was' : 'were'} already finished.`);
  if (r.not_found > 0) parts.push(`${r.not_found} could not be found.`);
  return parts.join(' ');
}

/** Shown above the alert list while rows are ticked: give all of them to one person (or take them off whoever has them), with an optional note kept in the audit log. Hidden for someone who cannot list people. */
export default function BulkAssignBar({
  alertIds,
  onDone,
  onClear,
  assign = alertsApi.bulkAssign,
}: {
  alertIds: string[];
  onDone: () => void;
  onClear: () => void;
  assign?: (body: { alert_ids: string[]; assignee_id: string | null; note?: string }) => Promise<BulkAssignResult>;
}) {
  const { data: people } = useSWR(alertIds.length > 0 ? 'bulk-assign-people' : null, () => tenantsApi.users().catch(() => null), { revalidateOnFocus: false });
  const [who, setWho] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  if (alertIds.length === 0 || !people) return null;
  const active = people.filter((p) => p.is_active);

  const submit = async () => {
    if (!who) return;
    setBusy(true);
    try {
      const result = await assign({ alert_ids: alertIds, assignee_id: who === 'none' ? null : who, ...(note.trim() ? { note: note.trim() } : {}) });
      toast.success(assignSummary(result));
      onDone();
      setWho('');
      setNote('');
      onClear();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not assign the alerts.');
    } finally {
      setBusy(false);
    }
  };

  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1';
  return (
    <div data-testid="bulk-assign-bar" className="flex flex-wrap items-center gap-2 border-b border-gray-800/60 bg-blue-500/5 px-4 py-2 text-xs text-gray-300">
      <span>Assign {alertIds.length} selected to</span>
      <select aria-label="Assign to" value={who} onChange={(e) => setWho(e.target.value)} className={field}>
        <option value="">Choose a person…</option>
        <option value="none">Nobody (unassign)</option>
        {active.map((p) => (
          <option key={p.id} value={p.id}>
            {p.email ?? p.account_name}
          </option>
        ))}
      </select>
      <input aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" maxLength={500} className={`${field} w-56`} />
      <button type="button" disabled={busy || !who} onClick={() => void submit()} className="rounded border border-blue-500/40 bg-blue-500/10 px-2 py-1 text-blue-200 hover:bg-blue-500/20 disabled:opacity-40">
        {busy ? 'Assigning…' : 'Assign alerts'}
      </button>
    </div>
  );
}
