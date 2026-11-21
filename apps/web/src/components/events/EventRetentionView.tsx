'use client';

/**
 * Settings > Data retention: how long each client's stored events are kept. Infinite by default; a client (or the default for everyone) can be set to 1, 3, 5, 7 or 10 years. Setting it deletes nothing. The preview
 * says how many events each client's retention has passed, and deleting them is a second step that names the number it will delete.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { msspApi } from '@/lib/api';

type Choice = 'infinite' | '1' | '3' | '5' | '7' | '10';
interface Retention {
  default: number | string;
  clients: Record<string, number | string>;
}
interface Preview {
  by_client: Record<string, number>;
  total: number;
}

const OPTIONS: [Choice, string][] = [
  ['infinite', 'Infinite'],
  ['1', '1 year'],
  ['3', '3 years'],
  ['5', '5 years'],
  ['7', '7 years'],
  ['10', '10 years'],
];
const asChoice = (v: number | string | undefined): Choice => (v === undefined ? 'infinite' : (String(v) as Choice));
/** The value to save for a choice (pure): a number of years, or "infinite". */
export const asValue = (c: Choice): number | string => (c === 'infinite' ? 'infinite' : Number(c));
const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

export function EventRetentionView() {
  const [clients, setClients] = useState<{ id: string; name: string }[]>([]);
  const [def, setDef] = useState<Choice>('infinite');
  const [per, setPer] = useState<Record<string, Choice>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [status, setStatus] = useState('');
  const [problem, setProblem] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        setClients((await msspApi.listChildren().catch(() => [])) as { id: string; name: string }[]);
        const res = await authFetch('/api/v1/events/retention');
        if (res.status === 403) throw new Error('Reading the retention needs the reports permission.');
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const r = (await res.json()) as Retention;
        setDef(asChoice(r.default));
        setPer(Object.fromEntries(Object.entries(r.clients).map(([k, v]) => [k, asChoice(v)])));
      } catch (e) {
        setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
  }, []);

  const save = async (): Promise<void> => {
    setProblem('');
    setStatus('Saving…');
    try {
      const body = { default: asValue(def), clients: Object.fromEntries(Object.entries(per).map(([k, v]) => [k, asValue(v)])) };
      const res = await authFetch('/api/v1/events/retention', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res.status === 403) throw new Error('Changing the retention needs the manage permission.');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setStatus('Saved. Nothing was deleted.');
      setPreview(null);
    } catch (e) {
      setStatus('');
      setProblem(e instanceof Error ? e.message : 'Could not save');
    }
  };

  const look = useCallback(async (): Promise<void> => {
    setProblem('');
    try {
      const res = await authFetch('/api/v1/events/retention/preview');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setPreview((await res.json()) as Preview);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not look');
    }
  }, []);

  const purge = async (): Promise<void> => {
    if (!preview || preview.total === 0) return;
    if (!window.confirm(`Delete ${preview.total} stored events that are past the retention of their client? This cannot be undone.`)) return;
    setProblem('');
    try {
      const res = await authFetch('/api/v1/events/retention/purge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: preview.total }) });
      if (res.status === 403) throw new Error('Deleting needs the manage permission.');
      if (res.status === 409) throw new Error(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? 'The number changed; look again.');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const done = (await res.json()) as { deleted: number };
      setStatus(`Deleted ${done.deleted} events.`);
      setPreview(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not delete');
    }
  };

  const nameOf = (id: string): string => (id === 'none' ? 'Events about no client' : (clients.find((c) => c.id === id)?.name ?? id));
  const select = (value: Choice, onChange: (c: Choice) => void, label: string) => (
    <select aria-label={label} className={field} value={value} onChange={(e) => onChange(e.target.value as Choice)}>
      {OPTIONS.map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  );

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Data retention</h1>
        <p className="mt-1 text-sm text-gray-400">How long the stored events of each client are kept. Infinite unless you choose a number of years. Choosing deletes nothing; deleting is a separate step below.</p>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      <div className="space-y-2">
        <label className="flex items-center gap-3 text-sm text-gray-200">
          <span className="w-64">Everyone (default)</span>
          {select(def, setDef, 'Default retention')}
        </label>
        {clients.map((c) => (
          <label key={c.id} className="flex items-center gap-3 text-sm text-gray-200">
            <span className="w-64 truncate">{c.name}</span>
            {select(per[c.id] ?? def, (v) => setPer({ ...per, [c.id]: v }), `Retention for ${c.name}`)}
          </label>
        ))}
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => void save()} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-100 hover:bg-gray-800">
            Save
          </button>
          <span className="text-xs text-gray-400" role="status">
            {status}
          </span>
        </div>
      </div>
      <div className="space-y-2 border-t border-gray-800 pt-4">
        <h2 className="text-lg font-semibold text-white">Events past their retention</h2>
        <button type="button" onClick={() => void look()} className="rounded border border-gray-700 px-3 py-1 text-sm text-gray-100 hover:bg-gray-800">
          Look
        </button>
        {preview && (
          <div data-testid="preview">
            {preview.total === 0 ? (
              <p className="text-sm text-gray-400">No stored event is past its retention.</p>
            ) : (
              <>
                <ul className="text-sm text-gray-200">
                  {Object.entries(preview.by_client).map(([id, n]) => (
                    <li key={id}>
                      {nameOf(id)}: {n}
                    </li>
                  ))}
                </ul>
                <button type="button" onClick={() => void purge()} className="mt-2 rounded border border-red-700 px-3 py-1 text-sm text-red-300 hover:bg-red-950">
                  Delete these {preview.total} events
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
