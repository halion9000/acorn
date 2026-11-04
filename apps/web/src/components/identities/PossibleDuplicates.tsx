'use client';

/**
 * Possible duplicates on the Identities page: pairs of people of one client who may be the same human but that no automatic rule joined (the same name, or the same name before the @ on another
 * domain). Each pair shows why it was suggested; the owner confirms it (Merge) or dismisses it (Not the same person, remembered, so it does not come back). Nothing happens without a press.
 * Backed by GET /api/v1/identities/duplicates and the existing merge routes.
 */
import { useState } from 'react';
import useSWR from 'swr';
import { identitiesApi, type IdentityDuplicate, type IdentityPerson } from '@/lib/api';
import { vendorLabel } from '@/components/mssp/ClientMapping';

export function duplicateTitle(count: number): string {
  return count === 0 ? 'No possible duplicates found' : `${count} possible duplicate${count === 1 ? '' : 's'}`;
}

function PersonColumn({ p }: { p: IdentityPerson }) {
  return (
    <div className="min-w-0 flex-1 rounded border border-gray-800 bg-gray-950/40 p-2">
      <div className="truncate text-sm font-medium text-gray-100">{p.display_name || p.email}</div>
      <div className="truncate text-xs text-gray-400">{p.email}</div>
      <div className="mt-1 text-xs text-gray-400">
        {p.tools.length > 0 ? p.tools.map((t) => vendorLabel(t)).join(', ') : 'No tool lists them'}
        {p.licensed === true ? ' · licensed' : ''}
        {p.enabled === false ? ' · disabled' : ''}
        {p.admin ? ' · administrator' : ''}
      </div>
    </div>
  );
}

function PairCard({ pair, onDone }: { pair: IdentityDuplicate; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.');
      setBusy(false);
    }
  };

  return (
    <li data-testid="duplicate-pair" className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
        <span className="font-medium text-gray-200">{pair.client_name ?? 'Client'}</span>
        <span className={pair.confidence === 'high' ? 'text-amber-300' : 'text-gray-400'}>{pair.confidence === 'high' ? 'Likely the same person' : 'Maybe the same person'}</span>
      </div>
      <div className="mt-2 flex flex-col gap-2 md:flex-row">
        <PersonColumn p={pair.a} />
        <PersonColumn p={pair.b} />
      </div>
      <ul className="mt-2 list-disc pl-5 text-xs text-gray-400">
        {pair.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {pair.both_licensed ? <p className="mt-1 text-xs text-amber-300">Both hold a licence: that is two paid seats. Merge only if one of them is really a spare.</p> : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {error}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-2">
        {confirming ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => identitiesApi.mergePeople({ client_id: pair.client_id, email: pair.a.email, with_email: pair.b.email }))}
              className="rounded-md border border-blue-500 bg-blue-500/20 px-2 py-1 text-xs text-white disabled:opacity-50"
            >
              Yes, merge them
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)} className="rounded-md border border-gray-700 px-2 py-1 text-xs text-gray-300">
              Cancel
            </button>
          </>
        ) : (
          <button type="button" disabled={busy} onClick={() => setConfirming(true)} className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-800 disabled:opacity-50">
            Merge these two
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void run(() => identitiesApi.separatePeople({ client_id: pair.client_id, email: pair.b.email, from_email: pair.a.email }))}
          className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-white hover:bg-gray-800 disabled:opacity-50"
        >
          Not the same person
        </button>
      </div>
    </li>
  );
}

export function PossibleDuplicates({ clientId, onChanged }: { clientId?: string; onChanged?: () => void }) {
  const { data, error, isLoading, mutate } = useSWR(['identity-duplicates', clientId ?? ''], () => identitiesApi.duplicates(clientId), { revalidateOnFocus: false });
  return (
    <section aria-label="Possible duplicates" className="space-y-2 rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-gray-200">{data ? duplicateTitle(data.total) : 'Possible duplicates'}</h2>
        <button type="button" onClick={() => void mutate()} className="text-xs text-gray-400 underline">
          Look again
        </button>
      </div>
      <p className="text-xs text-gray-500">People of one client who may be the same human but that nothing joined for certain. Merge only the ones you are sure of; the rest can be dismissed and will not come back.</p>
      {isLoading && !data ? <p className="text-sm text-gray-400">Looking…</p> : null}
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          Could not look for duplicates{error instanceof Error ? `: ${error.message}` : ''}.
        </p>
      ) : null}
      {data && data.items.length > 0 ? (
        <ul className="space-y-2">
          {data.items.map((pair) => (
            <PairCard
              key={`${pair.client_id}:${pair.a.email}:${pair.b.email}`}
              pair={pair}
              onDone={() => {
                void mutate();
                onChanged?.();
              }}
            />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
