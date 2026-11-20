'use client';

/**
 * Settings > Metrics people: tick the HaloPSA engineers to leave out of what the metrics pages show (staff metrics, pods, ticket updates, DialPad, meetings, the weekly comparison, the scorecard and the stale ticket
 * list by tech). Nothing is deleted: their tickets, hours and calls stay in the data and in every client total; they just do not appear as people.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { Page } from './kit';

interface Data {
  excluded: string[];
  engineers: string[];
}

/** The names to save: the ticked engineers plus anyone already excluded who is no longer in the data (so a name is never dropped by accident), without repeats (pure). */
export function toSave(ticked: Set<string>, engineers: string[], held: string[]): string[] {
  const known = new Set(engineers.map((e) => e.toLowerCase()));
  const keep = held.filter((h) => !known.has(h.toLowerCase()));
  return [...new Set([...ticked, ...keep])].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
}

export function ExcludedPeopleView() {
  const [data, setData] = useState<Data | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [problem, setProblem] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [denied, setDenied] = useState(false);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch('/api/v1/reports/metrics/excluded');
        if (!live) return;
        if (res.status === 403) return setDenied(true);
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const d = (await res.json()) as Data;
        setData(d);
        const held = new Set(d.excluded.map((n) => n.toLowerCase()));
        setTicked(new Set(d.engineers.filter((e) => held.has(e.toLowerCase()))));
      } catch (e) {
        if (live) setProblem(e instanceof Error ? e.message : 'Could not load');
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const save = async (): Promise<void> => {
    if (!data) return;
    setStatus('Saving…');
    try {
      const res = await authFetch('/api/v1/reports/metrics/excluded', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ excluded: toSave(ticked, data.engineers, data.excluded) }) });
      if (res.status === 403) return setStatus('Changing this needs the manage permission.');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      const saved = (await res.json()) as { excluded: string[] };
      setData({ ...data, excluded: saved.excluded });
      setStatus(`Saved: ${saved.excluded.length} excluded.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Could not save');
    }
  };

  const shown = (data?.engineers ?? []).filter((e) => e.toLowerCase().includes(filter.trim().toLowerCase()));
  const toggle = (name: string): void => {
    const next = new Set(ticked);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setTicked(next);
  };
  return (
    <Page
      title="Metrics people"
      subtitle="Tick the engineers to leave out of the metrics pages. Their tickets, hours and calls stay in the data and in every client total; they just do not show up as people."
      denied={denied}
      problem={problem}
      loading={data === null && !denied && !problem}
      empty={<p className="text-sm text-gray-400">CORE has not sent the weekly staff facts yet.</p>}
    >
      {data && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <input aria-label="Filter engineers" placeholder="Filter engineers" className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800" onClick={() => void save()}>
              Save
            </button>
            <span className="text-xs text-gray-400" role="status" data-testid="excluded-status">
              {status}
            </span>
          </div>
          <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3" data-testid="excluded-list">
            {shown.map((name) => (
              <li key={name}>
                <label className="flex items-center gap-2 text-sm text-gray-200">
                  <input type="checkbox" checked={ticked.has(name)} onChange={() => toggle(name)} />
                  {name}
                </label>
              </li>
            ))}
          </ul>
          {data.engineers.length === 0 && <p className="text-sm text-gray-400">No engineers yet.</p>}
        </div>
      )}
    </Page>
  );
}
