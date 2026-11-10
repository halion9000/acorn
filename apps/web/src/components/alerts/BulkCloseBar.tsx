'use client';

import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { alertsApi, type BulkCloseResult, type BulkCloseUndoResult } from '@/lib/api';

export const CLOSE_REASONS = ['Duplicate alerts', 'Handled in a ticket', 'Expected activity', 'Noise from the tool', 'Other'] as const;
export const OTHER = 'Other';

export type CloseStatus = 'resolved' | 'false_positive' | 'closed';

/** A status that finishes an alert: choosing one needs a reason from the list, so the false-positive rate and the audit log stay accurate (pure). */
export function needsCloseReason(status: string): status is CloseStatus {
  return status === 'resolved' || status === 'false_positive' || status === 'closed';
}
const STATUS_LABEL: Record<CloseStatus, string> = { resolved: 'Resolved', false_positive: 'False positive', closed: 'Closed' };

/** The reason to send: the preset, or what was typed when "Other" is chosen. Empty when there is not yet a usable reason (three characters at least). */
export function closeReason(preset: string, typed: string): string {
  const text = (preset === OTHER ? typed : preset).replace(/\s+/g, ' ').trim();
  return text.length >= 3 ? text : '';
}

/** "Closed 3 alerts as false positive: duplicates of the ticket. 1 was already finished." */
export function closeSummary(r: BulkCloseResult): string {
  const noun = (n: number) => `${n} alert${n === 1 ? '' : 's'}`;
  const parts = [`Closed ${noun(r.closed)} as ${STATUS_LABEL[r.status as CloseStatus]?.toLowerCase() ?? r.status}: ${r.reason}.`];
  if (r.already_finished > 0) parts.push(`${r.already_finished} ${r.already_finished === 1 ? 'was' : 'were'} already finished.`);
  if (r.not_found > 0) parts.push(`${r.not_found} could not be found.`);
  return parts.join(' ');
}

/** How long a bulk close can be undone, the same ten minutes the server allows. */
export const UNDO_MINUTES = 10;

/** "Put 3 alerts back. 1 had been changed since and was left alone." */
export function undoSummary(r: BulkCloseUndoResult): string {
  const noun = (n: number) => `${n} alert${n === 1 ? '' : 's'}`;
  const parts = [`Put ${noun(r.reopened)} back.`];
  if (r.changed_since > 0) parts.push(`${r.changed_since} had been changed since and ${r.changed_since === 1 ? 'was' : 'were'} left alone.`);
  if (r.too_late > 0) parts.push(`${r.too_late} ${r.too_late === 1 ? 'was' : 'were'} closed more than ${UNDO_MINUTES} minutes ago.`);
  if (r.not_found > 0) parts.push(`${r.not_found} could not be found.`);
  return parts.join(' ');
}

/** Shown above the alert list while rows are ticked: close all of them at once with one reason, which is kept in the audit log. */
export default function BulkCloseBar({
  alertIds,
  onDone,
  onClear,
  defaultStatus = 'resolved',
  close = alertsApi.bulkClose,
  undo = alertsApi.bulkCloseUndo,
}: {
  alertIds: string[];
  defaultStatus?: CloseStatus;
  onDone: () => void;
  onClear: () => void;
  close?: (body: { alert_ids: string[]; status: CloseStatus; reason: string }) => Promise<BulkCloseResult>;
  undo?: (body: { items: { id: string; status_from: string }[]; status: CloseStatus }) => Promise<BulkCloseUndoResult>;
}) {
  const [status, setStatus] = useState<CloseStatus>(defaultStatus);
  const [preset, setPreset] = useState<string>('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  // The last close, kept for ten minutes so a slip of the hand can be put back even after the selection is cleared.
  const [undoable, setUndoable] = useState<{ items: { id: string; status_from: string }[]; status: CloseStatus } | null>(null);
  useEffect(() => {
    if (!undoable) return;
    const timer = setTimeout(() => setUndoable(null), UNDO_MINUTES * 60_000);
    return () => clearTimeout(timer);
  }, [undoable]);
  const reason = closeReason(preset, typed);

  const putBack = async () => {
    if (!undoable) return;
    setBusy(true);
    try {
      toast.success(undoSummary(await undo(undoable)));
      setUndoable(null);
      onDone();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not put the alerts back.');
    } finally {
      setBusy(false);
    }
  };
  const undoStrip = undoable ? (
    <div data-testid="bulk-close-undo" className="flex flex-wrap items-center gap-2 border-b border-gray-800/60 bg-gray-800/40 px-4 py-2 text-xs text-gray-300">
      <span>
        Closed {undoable.items.length} alert{undoable.items.length === 1 ? '' : 's'}. This can be undone for {UNDO_MINUTES} minutes.
      </span>
      <button type="button" disabled={busy} onClick={() => void putBack()} className="rounded border border-gray-600 px-2 py-1 text-gray-100 hover:bg-gray-700 disabled:opacity-40">
        Undo
      </button>
    </div>
  ) : null;
  if (alertIds.length === 0) return undoStrip;

  const submit = async () => {
    if (!reason) return;
    setBusy(true);
    try {
      const result = await close({ alert_ids: alertIds, status, reason });
      toast.success(closeSummary(result));
      setUndoable(result.closed_items && result.closed_items.length > 0 ? { items: result.closed_items, status } : null);
      onDone();
      setPreset('');
      setTyped('');
      onClear();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not close the alerts.');
    } finally {
      setBusy(false);
    }
  };

  const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1';
  return (
    <>
    {undoStrip}
    <div data-testid="bulk-close-bar" className="flex flex-wrap items-center gap-2 border-b border-gray-800/60 bg-amber-500/5 px-4 py-2 text-xs text-gray-300">
      <span>Close {alertIds.length} selected as</span>
      <select aria-label="Close as" value={status} onChange={(e) => setStatus(e.target.value as CloseStatus)} className={field}>
        {(Object.keys(STATUS_LABEL) as CloseStatus[]).map((s) => (
          <option key={s} value={s}>
            {STATUS_LABEL[s]}
          </option>
        ))}
      </select>
      <select aria-label="Reason" value={preset} onChange={(e) => setPreset(e.target.value)} className={field}>
        <option value="">Choose a reason…</option>
        {CLOSE_REASONS.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      {preset === OTHER && <input aria-label="Other reason" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Why" maxLength={500} className={`${field} w-56`} />}
      <button
        type="button"
        disabled={busy || !reason}
        onClick={() => void submit()}
        className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
      >
        {busy ? 'Closing…' : 'Close alerts'}
      </button>
    </div>
    </>
  );
}
