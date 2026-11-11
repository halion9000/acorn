'use client';

/**
 * "Add to HaloPSA" for a person who has a cloud account but no HaloPSA user. Shown only to someone who holds the permission (the server checks it again) and only for a person the HaloPSA check flags. A press opens an
 * "Are you sure?" window; Yes queues the request for CORE, which creates the user under the client's HaloPSA client and reports back. The line under the button is what happened, in CORE's words, never "Done" before CORE says so.
 */

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { authApi, identitiesApi, type HaloUserRequest } from '@/lib/api';
import { safeDistance } from '@/lib/safe-date';

const STATUS_TEXT: Record<string, { text: string; className: string }> = {
  pending: { text: 'Waiting for CORE', className: 'text-amber-300' },
  running: { text: 'Running', className: 'text-amber-300' },
  done: { text: 'Done', className: 'text-emerald-300' },
  failed: { text: 'Failed', className: 'text-red-300' },
};

/** Whether the button is offered: the person has a cloud account and no HaloPSA user, and the viewer may respond to identities (pure). */
export function canOfferAddToHalo(capabilities: string[] | undefined, haloCheck: string | null | undefined): boolean {
  return (capabilities ?? []).includes('respond_identities') && haloCheck === 'cloud_not_in_halo';
}

export function AddToHalo({ clientId, email, name, haloCheck }: { clientId: string; email: string; name?: string | null; haloCheck?: string | null }) {
  const [cached, setCached] = useState<string[]>([]);
  useEffect(() => setCached(authApi.currentUser()?.capabilities ?? []), []);
  const { data: fresh } = useSWR('my-capabilities', () => authApi.freshCapabilities(), { revalidateOnFocus: false, dedupingInterval: 60_000, shouldRetryOnError: false });
  const allowed = canOfferAddToHalo(fresh ?? cached, haloCheck);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const { data, mutate } = useSWR(allowed ? ['halo-user', clientId, email] : null, () => identitiesApi.haloUserRequests(clientId, email), {
    refreshInterval: (latest) => (latest?.some((i) => i.status === 'pending' || i.status === 'running') ? 5_000 : 0),
    revalidateOnFocus: false,
  });
  if (!allowed) return null;
  const last: HaloUserRequest | undefined = data?.[0];

  async function confirm() {
    setBusy(true);
    setProblem('');
    try {
      await identitiesApi.requestHaloUser({ client_id: clientId, email, name: name ?? '', confirm: true });
      setAsking(false);
      await mutate();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'The request was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="add-to-halo">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">HaloPSA</h4>
      <button type="button" onClick={() => { setProblem(''); setAsking(true); }} className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800">
        Add to HaloPSA
      </button>
      <p className="mt-1 text-[11px] text-gray-500">Creates a HaloPSA user for this person under the client&apos;s main site, carried out by CORE.</p>
      {last && (
        <p className="mt-1 text-xs text-gray-300" data-testid="add-to-halo-status">
          <span className={(STATUS_TEXT[last.status] ?? STATUS_TEXT.pending!).className}>{(STATUS_TEXT[last.status] ?? STATUS_TEXT.pending!).text}</span>
          <span className="text-gray-500"> · {safeDistance(last.created_at, { addSuffix: true })}</span>
          {last.message ? <span className="block text-gray-400">{last.message}</span> : null}
        </p>
      )}
      {asking && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Are you sure?" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Are you sure?</h3>
            <p className="mt-2 text-sm text-gray-300">This adds {email} to HaloPSA as a user of this client. HaloPSA may send them a welcome message, depending on your settings there.</p>
            {problem && <p className="mt-2 text-sm text-red-300">{problem}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setAsking(false)} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              <button type="button" onClick={() => void confirm()} disabled={busy} className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500">
                {busy ? 'Sending…' : 'Yes, add to HaloPSA'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
