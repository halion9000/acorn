'use client';

/**
 * Shown above the alert list when the Stale filter is on. Stale alerts are ones nobody touched for a month (not critical or high, in no case): they are set aside, not deleted. This says how many and why,
 * and offers the two bulk actions: put them all back as they were, or close them all. Both ask first and apply to the client picked in the list (or to every client when none is).
 */

import { useState } from 'react';
import useSWR from 'swr';
import { alertsApi } from '@/lib/api';

type Action = 'restore' | 'close';

export function StaleReview({ clientId, onChanged }: { clientId?: string; onChanged: () => void }) {
  const { data, mutate } = useSWR(['alert-stale', clientId ?? 'all'], () => alertsApi.staleSummary(clientId), { revalidateOnFocus: false });
  const [asking, setAsking] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [done, setDone] = useState('');

  async function confirm() {
    if (!asking) return;
    setBusy(true);
    setProblem('');
    try {
      const body = { ...(clientId ? { client_id: clientId } : {}), confirm: true };
      const out = asking === 'restore' ? await alertsApi.restoreStale(body) : await alertsApi.closeStale(body);
      setDone(`${out.changed} alert${out.changed === 1 ? '' : 's'} ${asking === 'restore' ? 'put back' : 'closed'}.`);
      setAsking(null);
      await mutate();
      onChanged();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  const scope = clientId ? "this client's" : 'every client\'s';
  return (
    <section className="mb-3 rounded-lg border border-gray-800 bg-gray-900/60 p-3" data-testid="stale-review">
      <p className="text-sm text-gray-200">
        {data ? `${data.total} stale alert${data.total === 1 ? '' : 's'}` : 'Stale alerts'}
        {data ? <span className="text-gray-500"> · set aside after {data.days} days with no activity</span> : null}
      </p>
      <p className="mt-1 text-xs text-gray-500">
        {data
          ? `Critical and high alerts${data.exempt_severities.length ? ` (${data.exempt_severities.join(', ')})` : ''} and alerts in a case are never set aside. Nothing is deleted: put them back as they were, or close them.`
          : 'Nothing is deleted: put them back as they were, or close them.'}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" disabled={!data?.total} onClick={() => setAsking('restore')} className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
          Put all back
        </button>
        <button type="button" disabled={!data?.total} onClick={() => setAsking('close')} className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
          Close all
        </button>
        {done && <span className="text-xs text-emerald-300">{done}</span>}
      </div>
      {asking && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Are you sure?" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Are you sure?</h3>
            <p className="mt-2 text-sm text-gray-300">
              {asking === 'restore'
                ? `This puts ${scope} ${data?.total ?? ''} stale alerts back in the lists as they were. They count as quiet from now, so they are not set aside again for ${data?.days ?? 30} days.`
                : `This closes ${scope} ${data?.total ?? ''} stale alerts. You cannot undo it in bulk.`}
            </p>
            {problem && <p className="mt-2 text-sm text-red-300">{problem}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setAsking(null)} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              <button type="button" onClick={() => void confirm()} disabled={busy} className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
                {busy ? 'Working…' : asking === 'restore' ? 'Yes, put them back' : 'Yes, close them'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
