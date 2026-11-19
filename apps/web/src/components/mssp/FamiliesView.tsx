'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { msspApi, type ChildTenant, type ClientFamily } from '@/lib/api';
import { EmptyState, PageHeader } from '@/components/ui/kit';

/** Settings > Client families: a parent company and its linked child clients (roadmap huntress-family). Only links clients; nothing is moved or merged. */
export default function FamiliesView() {
  const [families, setFamilies] = useState<ClientFamily[] | null>(null);
  const [clients, setClients] = useState<ChildTenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [f, c] = await Promise.all([msspApi.listFamilies(), msspApi.listChildren()]);
      setFamilies(f);
      setClients(c);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Could not load the families.');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const inFamily = new Set((families ?? []).flatMap((f) => f.client_ids));
  const free = clients.filter((c) => !inFamily.has(c.id));

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      await load();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const create = () =>
    act(async () => {
      await msspApi.createFamily(name.trim(), picked);
      setName('');
      setPicked([]);
    });

  return (
    <div className="space-y-6 p-6" data-testid="families">
      <PageHeader
        title="Client families"
        subtitle="Link a parent company and its child clients, such as New Waterloo and its NW clients. Every client keeps its own devices, alerts and numbers; the link only lets a record that belongs to the group be recognized under a sibling."
      />
      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}
      <section className="space-y-3 rounded-xl border border-gray-800 bg-gray-900 p-4" aria-label="New family">
        <h2 className="text-sm font-semibold text-white">New family</h2>
        <label className="block text-sm text-gray-300">
          Family name
          <input aria-label="Family name" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 block w-full max-w-sm rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100" />
        </label>
        <fieldset className="text-sm text-gray-300">
          <legend className="mb-1">Clients in it (a client can be in one family)</legend>
          {free.length === 0 ? (
            <p className="text-xs text-gray-400">Every client is already in a family.</p>
          ) : (
            <div className="grid max-h-56 gap-1 overflow-auto sm:grid-cols-2 lg:grid-cols-3">
              {free.map((c) => (
                <label key={c.id} className="flex items-center gap-2">
                  <input type="checkbox" checked={picked.includes(c.id)} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.id] : p.filter((x) => x !== c.id)))} />
                  {c.name}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <button type="button" disabled={busy || name.trim().length < 2} onClick={() => void create()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          Create family
        </button>
      </section>
      {families === null && !error ? (
        <p role="status" className="text-sm text-gray-400">
          Loading…
        </p>
      ) : families && families.length === 0 ? (
        <EmptyState title="No families yet" why="Create one above to link a parent company with its child clients." />
      ) : (
        <ul className="space-y-3">
          {(families ?? []).map((f) => (
            <li key={f.id} className="rounded-xl border border-gray-800 bg-gray-900 p-4" data-testid="family">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-white">{f.name}</h3>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(`Delete the family ${f.name}? Its clients are not touched.`)) void act(() => msspApi.deleteFamily(f.id));
                  }}
                  className="text-xs text-red-300 hover:underline"
                >
                  Delete {f.name}
                </button>
              </div>
              <ul className="mt-2 flex flex-wrap gap-2 text-sm text-gray-200">
                {f.client_ids.map((id, i) => (
                  <li key={id} className="flex items-center gap-1 rounded-full border border-gray-700 px-2 py-0.5">
                    {f.clients[i]}
                    <button type="button" aria-label={`Take ${f.clients[i]} out of ${f.name}`} disabled={busy} className="text-gray-400 hover:text-white" onClick={() => void act(() => msspApi.changeFamily(f.id, { client_ids: f.client_ids.filter((x) => x !== id) }))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
              {free.length > 0 && (
                <label className="mt-2 block text-xs text-gray-400">
                  Add a client to {f.name}
                  <select
                    aria-label={`Add a client to ${f.name}`}
                    className="ml-2 rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100"
                    value=""
                    disabled={busy}
                    onChange={(e) => {
                      if (e.target.value) void act(() => msspApi.changeFamily(f.id, { client_ids: [...f.client_ids, e.target.value] }));
                    }}
                  >
                    <option value="">Pick a client</option>
                    {free.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-gray-500">
        <Link href="/settings/client-mapping" className="underline">
          Client mapping
        </Link>{' '}
        links each tool&apos;s clients to yours; a family links your own clients to each other.
      </p>
    </div>
  );
}
