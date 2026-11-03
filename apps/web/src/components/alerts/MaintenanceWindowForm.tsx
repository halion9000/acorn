'use client';

import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { alertsApi, msspApi } from '@/lib/api';

export const WINDOW_HOURS = [1, 2, 4, 8, 24, 48, 72];

/** Start a maintenance window: one client's alerts are hidden (critical ones never) from now or a chosen time for up to 72 hours, and come back when it ends. */
export function MaintenanceWindowForm({ onStarted }: { onStarted: () => void }) {
  const { data: clients } = useSWR('mssp-children', () => msspApi.listChildren().catch(() => []), { revalidateOnFocus: false });
  const [clientId, setClientId] = useState('');
  const [hours, setHours] = useState(4);
  const [startsAt, setStartsAt] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    try {
      const out = await alertsApi.startMaintenance({ clientId, hours, startsAt: startsAt ? new Date(startsAt).toISOString() : undefined, reason: reason.trim() || undefined });
      const n = out.hidden_alerts ?? 0;
      toast.success(startsAt ? 'Maintenance window scheduled' : `Maintenance window started${n > 0 ? `: ${n} alert${n === 1 ? '' : 's'} hidden` : ''}`);
      setReason('');
      setStartsAt('');
      onStarted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start the maintenance window');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Maintenance window" className="rounded-lg border border-gray-800 p-4">
      <h2 className="text-sm font-medium text-gray-100">Planned maintenance</h2>
      <p className="mt-0.5 text-xs text-gray-500">Hide one client&rsquo;s alerts while you work on its systems. Critical alerts are never hidden, a window lasts at most 72 hours, and everything comes back when it ends.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-400">
          Client
          <select aria-label="Client" value={clientId} onChange={(e) => setClientId(e.target.value)} className="mt-1 block rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white">
            <option value="">Choose a client</option>
            {(clients ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          For
          <select aria-label="Hours" value={hours} onChange={(e) => setHours(Number(e.target.value))} className="mt-1 block rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white">
            {WINDOW_HOURS.map((h) => (
              <option key={h} value={h}>
                {h} hour{h === 1 ? '' : 's'}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Starts (leave empty for now)
          <input aria-label="Starts" type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} className="mt-1 block rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white" />
        </label>
        <label className="text-xs text-gray-400">
          Reason
          <input aria-label="Reason" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="e.g. server migration" className="mt-1 block w-56 rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white placeholder:text-gray-500" />
        </label>
        <button type="button" disabled={!clientId || busy} onClick={() => void start()} className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
          Start maintenance window
        </button>
      </div>
    </section>
  );
}
