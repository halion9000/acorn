'use client';

/**
 * The addresses of one person, and the two ways to correct them by hand: "Merge with another person" (search the same client, confirm) and, for each address that was folded in, "Not the same person".
 * The automatic rules do most of the work (a name that is another address, a guest sign-in name, the .onmicrosoft.com twin); this is for the rest. Both are stored per client and survive every refresh.
 */

import { useEffect, useState } from 'react';
import { mutate as refresh } from 'swr';
import { identitiesApi, type IdentityPerson, type PeopleDecision } from '@/lib/api';

/** Refreshes the list and every opened person after a merge or a split. */
export function refreshPeople(): Promise<unknown> {
  return refresh((key) => Array.isArray(key) && (key[0] === 'identities' || key[0] === 'identity'));
}

export function MergePanel({
  person,
  onChanged = refreshPeople,
}: {
  person: Pick<IdentityPerson, 'client_id' | 'email' | 'display_name' | 'aliases'>;
  onChanged?: () => Promise<unknown> | void;
}) {
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [results, setResults] = useState<IdentityPerson[]>([]);
  const [chosen, setChosen] = useState<IdentityPerson | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [decisions, setDecisions] = useState<PeopleDecision[]>([]);
  const [reload, setReload] = useState(0);

  // The hand decisions about this person, so a "not the same person" mark (which nothing else shows) can be taken back.
  useEffect(() => {
    let live = true;
    identitiesApi
      .decisions(person.client_id, person.email)
      .then((r) => live && setDecisions(r.items))
      .catch(() => live && setDecisions([]));
    return () => {
      live = false;
    };
  }, [person.client_id, person.email, reload]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (!searching || debounced.length < 2) {
      setResults([]);
      return;
    }
    let live = true;
    identitiesApi
      .list({ clientId: person.client_id, search: debounced, pageSize: 8 })
      .then((r) => live && setResults(r.items.filter((p) => p.email !== person.email)))
      .catch(() => live && setResults([]));
    return () => {
      live = false;
    };
  }, [searching, debounced, person.client_id, person.email]);

  async function run(job: () => Promise<unknown>) {
    setBusy(true);
    setProblem('');
    try {
      await job();
      setReload((n) => n + 1);
      setChosen(null);
      setSearching(false);
      setQ('');
      await onChanged();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  const aliases = person.aliases ?? [];
  return (
    <section data-testid="merge-panel">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-500">Addresses</h4>
      <ul className="space-y-1 text-sm">
        <li className="text-gray-200">{person.email}</li>
        {aliases.map((a) => (
          <li key={a.email} className="flex flex-wrap items-center gap-2 text-gray-300">
            <span>{a.email}</span>
            <span className="text-xs text-gray-500">({a.reason})</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => identitiesApi.separatePeople({ client_id: person.client_id, email: a.email, from_email: person.email }))}
              className="text-xs text-blue-300 hover:text-blue-200"
              aria-label={`${a.email} is not the same person`}
            >
              Not the same person
            </button>
          </li>
        ))}
      </ul>
      {problem && !chosen && <p className="mt-1 text-xs text-red-300">{problem}</p>}

      {decisions.length > 0 && (
        <div className="mt-2" data-testid="merge-decisions">
          <h5 className="text-xs font-semibold uppercase text-gray-500">Your decisions</h5>
          <ul className="mt-1 space-y-1 text-xs text-gray-300">
            {decisions.map((d) => (
              <li key={`${d.address_a}|${d.address_b}`} className="flex flex-wrap items-center gap-2">
                <span>
                  {d.kind === 'merge' ? 'Joined by you: ' : 'Kept apart by you: '}
                  {d.address_a} and {d.address_b}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => identitiesApi.removeDecision(person.client_id, d.address_a, d.address_b))}
                  className="text-blue-300 hover:text-blue-200"
                  aria-label={`Take back: ${d.address_a} and ${d.address_b}`}
                >
                  Take back
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!searching ? (
        <button type="button" onClick={() => setSearching(true)} className="mt-2 text-xs text-blue-300 hover:text-blue-200">
          Merge with another person…
        </button>
      ) : (
        <div className="mt-2">
          <input
            autoFocus
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name or address, same client"
            aria-label="Find the person to merge with"
            className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-200"
          />
          <ul className="mt-1 space-y-0.5">
            {results.map((r) => (
              <li key={r.key}>
                <button type="button" onClick={() => setChosen(r)} className="w-full rounded px-1 py-0.5 text-left text-xs text-gray-200 hover:bg-gray-800">
                  {r.display_name && !r.display_name.includes('@') ? `${r.display_name} · ` : ''}
                  {r.email}
                  <span className="text-gray-500">
                    {' '}
                    · {r.tools.length} tool{r.tools.length === 1 ? '' : 's'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => {
              setSearching(false);
              setQ('');
            }}
            className="mt-1 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        </div>
      )}

      {chosen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div role="dialog" aria-modal="true" aria-label="Merge these two?" className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-5 shadow-xl">
            <h3 className="text-base font-semibold text-gray-100">Merge these two?</h3>
            <p className="mt-2 text-sm text-gray-300">
              {person.email} and {chosen.email} become one person: their tools, alerts and backups are shown together. You can split them again with &quot;Not the same person&quot;.
            </p>
            {problem && <p className="mt-2 text-sm text-red-300">{problem}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setChosen(null)} disabled={busy} className="rounded border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800">
                No, cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void run(() => identitiesApi.mergePeople({ client_id: person.client_id, email: person.email, with_email: chosen.email }))}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
              >
                {busy ? 'Merging…' : 'Yes, merge'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
