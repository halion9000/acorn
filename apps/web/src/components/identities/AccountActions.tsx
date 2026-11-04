'use client';

/**
 * Account actions for one person: sign out everywhere, block sign-in, allow sign-in. Shown only to someone who holds the permission (the server checks it again) and only for a person Microsoft 365
 * knows. A press opens an "Are you sure?" window; Yes queues the request for CORE, which carries it out through CIPP under its own rules. The list under the buttons is what happened to recent
 * requests, in CORE's words: "Waiting for CORE", "Running", "Done" or "Failed", never "Done" before CORE says so.
 */

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { authApi, identitiesApi, type AccountActionItem, type AccountActionKind } from '@/lib/api';
import { safeDistance } from '@/lib/safe-date';

const ACTIONS: { kind: AccountActionKind; label: string; confirm: (who: string) => string; danger: boolean }[] = [
  {
    kind: 'revoke_sessions',
    label: 'Sign out everywhere',
    confirm: (who) => `This signs ${who} out of Microsoft 365 on every device. They will have to sign in again.`,
    danger: false,
  },
  {
    kind: 'disable_user',
    label: 'Block sign-in',
    confirm: (who) => `This blocks ${who} from signing in to Microsoft 365 until someone allows it again.`,
    danger: true,
  },
  {
    kind: 'enable_user',
    label: 'Allow sign-in',
    confirm: (who) => `This lets ${who} sign in to Microsoft 365 again.`,
    danger: false,
  },
];

const STATUS_TEXT: Record<AccountActionItem['status'], { text: string; className: string }> = {
  pending: { text: 'Waiting for CORE', className: 'text-amber-300' },
  running: { text: 'Running', className: 'text-amber-300' },
  done: { text: 'Done', className: 'text-emerald-300' },
  failed: { text: 'Failed', className: 'text-red-300' },
};

/** Whether this person's page offers the buttons: a client's person that Microsoft 365 (through CIPP) knows. */
export function canOfferAccountActions(capabilities: string[] | undefined, knownTo: string[]): boolean {
  return (capabilities ?? []).includes('respond_identities') && knownTo.includes('cipp');
}

export function AccountActions({ clientId, email, knownTo }: { clientId: string; email: string; knownTo: string[] }) {
  // What the person may do is asked of the server (shared by every row, once a minute), not read only from the copy kept at sign-in: that copy predates a permission added later, and the buttons stayed hidden until
  // the next sign-in. The cached copy is used until the answer arrives, and if the server cannot be asked.
  const [cached, setCached] = useState<string[]>([]);
  useEffect(() => setCached(authApi.currentUser()?.capabilities ?? []), []);
  const { data: fresh } = useSWR('my-capabilities', () => authApi.freshCapabilities(), { revalidateOnFocus: false, dedupingInterval: 60_000, shouldRetryOnError: false });
  const allowed = canOfferAccountActions(fresh ?? cached, knownTo);
  const [asking, setAsking] = useState<AccountActionKind | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const { data, mutate } = useSWR(allowed ? ['account-actions', clientId, email] : null, () => identitiesApi.accountActions(clientId, email), {
    refreshInterval: (latest) => (latest?.items.some((i) => i.status === 'pending' || i.status === 'running') ? 5_000 : 0),
    revalidateOnFocus: false,
  });
  if (!allowed) return null;
  const chosen = ACTIONS.find((a) => a.kind === asking) ?? null;

  async function confirm() {
    if (!chosen) return;
    setBusy(true);
    setProblem('');
    try {
      await identitiesApi.requestAccountAction({ client_id: clientId, email, action: chosen.kind, confirm: true });
      setAsking(null);
      await mutate();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'The request was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="account-actions">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">Account actions</h4>
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((a) => (
          <button
            key={a.kind}
            type="button"
            onClick={() => {
              setProblem('');
              setAsking(a.kind);
            }}
            className={`rounded border px-2 py-1 text-xs ${a.danger ? 'border-red-500/40 text-red-300 hover:bg-red-500/10' : 'border-gray-600 text-gray-200 hover:bg-gray-800'}`}
          >
            {a.label}
          </button>
        ))}
      </div>
      <p className="mt-1 text-[11px] text-gray-500">Carried out by CORE through CIPP, for clients CORE is switched on for. Protected accounts are refused.</p>
      {problem && !chosen && <p className="mt-1 text-xs text-red-300">{problem}</p>}

      {(data?.items ?? []).length > 0 && (
        <ul className="mt-2 space-y-1" data-testid="account-action-list">
          {data!.items.map((i) => (
            <li key={i.id} className="text-xs text-gray-300">
              {i.label} <span className={STATUS_TEXT[i.status].className}>{STATUS_TEXT[i.status].text}</span>
              <span className="text-gray-500">
                {i.requested_by ? ` · asked by ${i.requested_by}` : ''} · {safeDistance(i.created_at, { addSuffix: true })}
              </span>
              {i.message ? <span className="block text-gray-400">{i.message}</span> : null}
            </li>
          ))}
        </ul>
      )}

      {chosen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Are you sure?" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Are you sure?</h3>
            <p className="mt-2 text-sm text-gray-300">{chosen.confirm(email)}</p>
            <p className="mt-2 text-xs text-gray-500">CORE refuses it for protected accounts and for clients it is not switched on for, and says so here.</p>
            {problem && <p className="mt-2 text-sm text-red-300">{problem}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setAsking(null)} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              <button type="button" onClick={() => void confirm()} disabled={busy} className={`rounded px-3 py-1.5 text-sm font-medium text-white ${chosen.danger ? 'bg-red-600 hover:bg-red-500' : 'bg-blue-600 hover:bg-blue-500'}`}>
                {busy ? 'Sending…' : `Yes, ${chosen.label.toLowerCase()}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
