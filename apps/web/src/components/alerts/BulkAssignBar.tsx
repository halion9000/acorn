'use client';

import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import useSWR from 'swr';
import { alertsApi, tenantsApi, type BulkAssignResult, type BulkAssignUndoResult } from '@/lib/api';
import { UNDO_MINUTES } from './BulkCloseBar';

/** "Assigned 3 alerts to amy@acme.com. 1 was already finished." / "Unassigned 3 alerts." */
export function assignSummary(r: BulkAssignResult): string {
  const noun = (n: number) => `${n} alert${n === 1 ? '' : 's'}`;
  const parts = [r.assignee_name ? `Assigned ${noun(r.assigned)} to ${r.assignee_name}.` : `Unassigned ${noun(r.assigned)}.`];
  if (r.already_finished > 0) parts.push(`${r.already_finished} ${r.already_finished === 1 ? 'was' : 'were'} already finished.`);
  if (r.not_found > 0) parts.push(`${r.not_found} could not be found.`);
  return parts.join(' ');
}

/** "Put 3 alerts back. 1 had been changed since and was left alone." */
export function assignUndoSummary(r: BulkAssignUndoResult): string {
  const noun = (n: number) => `${n} alert${n === 1 ? '' : 's'}`;
  const parts = [`Put ${noun(r.restored)} back.`];
  if (r.changed_since > 0) parts.push(`${r.changed_since} had been changed since and ${r.changed_since === 1 ? 'was' : 'were'} left alone.`);
  if (r.too_late > 0) parts.push(`${r.too_late} ${r.too_late === 1 ? 'was' : 'were'} assigned more than ${UNDO_MINUTES} minutes ago.`);
  if (r.not_found > 0) parts.push(`${r.not_found} could not be found.`);
  return parts.join(' ');
}

/** Shown above the alert list while rows are ticked: give all of them to one person (or take them off whoever has them), with an optional note kept in the audit log. Hidden for someone who cannot list people. */
export default function BulkAssignBar({
  alertIds,
  onDone,
  onClear,
  assign = alertsApi.bulkAssign,
  undo = alertsApi.bulkAssignUndo,
}: {
  alertIds: string[];
  onDone: () => void;
  onClear: () => void;
  assign?: (body: { alert_ids: string[]; assignee_id: string | null; note?: string }) => Promise<BulkAssignResult>;
  undo?: (body: { items: NonNullable<BulkAssignResult['assigned_items']>; assignee_id: string | null }) => Promise<BulkAssignUndoResult>;
}) {
  const { data: people } = useSWR(alertIds.length > 0 ? 'bulk-assign-people' : null, () => tenantsApi.users().catch(() => null), { revalidateOnFocus: false });
  const [who, setWho] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  // The last assign, kept for ten minutes so a slip of the hand can be put back even after the selection is cleared.
  const [undoable, setUndoable] = useState<{ items: NonNullable<BulkAssignResult['assigned_items']>; assignee_id: string | null } | null>(null);
  useEffect(() => {
    if (!undoable) return;
    const timer = setTimeout(() => setUndoable(null), UNDO_MINUTES * 60_000);
    return () => clearTimeout(timer);
  }, [undoable]);

  const putBack = async () => {
    if (!undoable) return;
    setBusy(true);
    try {
      toast.success(assignUndoSummary(await undo(undoable)));
      setUndoable(null);
      onDone();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not put the alerts back.');
    } finally {
      setBusy(false);
    }
  };
  const undoStrip = undoable ? (
    <div data-testid="bulk-assign-undo" className="flex flex-wrap items-center gap-2 border-b border-gray-800/60 bg-gray-800/40 px-4 py-2 text-xs text-gray-300">
      <span>
        Changed who has {undoable.items.length} alert{undoable.items.length === 1 ? '' : 's'}. This can be undone for {UNDO_MINUTES} minutes.
      </span>
      <button type="button" disabled={busy} onClick={() => void putBack()} className="rounded border border-gray-600 px-2 py-1 text-gray-100 hover:bg-gray-700 disabled:opacity-40">
        Undo
      </button>
    </div>
  ) : null;
  if (alertIds.length === 0 || !people) return undoStrip;
  const active = people.filter((p) => p.is_active);

  const submit = async () => {
    if (!who) return;
    setBusy(true);
    try {
      const result = await assign({ alert_ids: alertIds, assignee_id: who === 'none' ? null : who, ...(note.trim() ? { note: note.trim() } : {}) });
      toast.success(assignSummary(result));
      setUndoable(result.assigned_items && result.assigned_items.length > 0 ? { items: result.assigned_items, assignee_id: who === 'none' ? null : who } : null);
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
    <>
    {undoStrip}
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
    </>
  );
}
