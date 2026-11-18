'use client';

/**
 * Settings > Finance > Client groups: client names filed under one Primary Name. A client is sometimes billed or worked under more than one name (a company and a brand, a renamed company, the customers QuickBooks
 * books under one client); Net income adds the names of a group into one client, in HaloPSA's numbers and in QuickBooks'. A group is made or changed by ticking the names that belong to it (every name Net income has
 * seen is listed); a name ticked that is in another group moves to this one, and a name un-ticked is taken out. Backed by /api/v1/finance/client-groups and /client-names.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

export interface Group {
  primary: string;
  members: string[];
}
export interface KnownName {
  name: string;
  group: string | null;
}

/** The rows to send to file a group (pure): every ticked name that was not in it, or all of them when the Primary Name changed, and an empty Primary Name for each name that was in it and is no longer ticked. */
export function groupChanges(original: { primary: string; members: string[] } | null, primary: string, ticked: string[]): { name: string; primary: string }[] {
  const was = new Set(original?.members ?? []);
  const renamed = original !== null && original.primary !== primary;
  const rows: { name: string; primary: string }[] = [];
  for (const name of ticked) if (!was.has(name) || renamed) rows.push({ name, primary });
  for (const name of was) if (!ticked.includes(name)) rows.push({ name, primary: '' });
  return rows;
}

/** The names that contain what was typed, in any case, ticked ones first (pure). */
export function filterNames(names: KnownName[], text: string, ticked: Set<string>): KnownName[] {
  const needle = text.trim().toLowerCase();
  const hit = needle ? names.filter((n) => n.name.toLowerCase().includes(needle)) : names;
  return [...hit].sort((a, b) => Number(ticked.has(b.name)) - Number(ticked.has(a.name)) || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';

/** The tick list for one group: the Primary Name, a search box and a checkbox for every known name. */
function Picker({ original, names, busy, onSave, onCancel }: { original: Group | null; names: KnownName[]; busy: boolean; onSave: (rows: { name: string; primary: string }[]) => void; onCancel: () => void }) {
  const [primary, setPrimary] = useState(original?.primary ?? '');
  const [text, setText] = useState('');
  const [ticked, setTicked] = useState<Set<string>>(new Set(original?.members ?? []));
  const shown = useMemo(() => filterNames(names, text, ticked), [names, text, ticked]);
  const toggle = (name: string) => setTicked((t) => (t.has(name) ? new Set([...t].filter((n) => n !== name)) : new Set([...t, name])));
  const rows = groupChanges(original, primary.trim(), [...ticked]);
  const ok = primary.trim() !== '' && ticked.size > 0 && rows.length > 0;
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-gray-700 bg-gray-900/50 p-3" data-testid="group-picker">
      <label className="block text-xs text-gray-400">
        Primary Name (what the client is called on Net income)
        <input aria-label="Primary Name" className={`${input} mt-1 block w-full max-w-md`} value={primary} onChange={(e) => setPrimary(e.target.value)} />
      </label>
      <input aria-label="Find a name" placeholder="Find a name" className={`${input} block w-full max-w-md`} value={text} onChange={(e) => setText(e.target.value)} />
      <ul className="max-h-64 overflow-y-auto rounded border border-gray-800 p-2 text-sm text-gray-200">
        {shown.length === 0 ? <li className="text-xs text-gray-500">No name matches.</li> : null}
        {shown.map((n) => (
          <li key={n.name}>
            <label className="flex items-center gap-2 py-0.5">
              <input type="checkbox" checked={ticked.has(n.name)} onChange={() => toggle(n.name)} aria-label={n.name} />
              <span>{n.name}</span>
              {n.group && n.group !== original?.primary ? <span className="text-xs text-gray-500">(now in {n.group})</span> : null}
            </label>
          </li>
        ))}
      </ul>
      <p className="text-xs text-gray-500">{ticked.size} name{ticked.size === 1 ? '' : 's'} ticked.</p>
      <div className="flex gap-2">
        <button type="button" className={ghost} disabled={busy || !ok} onClick={() => onSave(rows)}>
          Save group
        </button>
        <button type="button" className={ghost} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export function ClientGroupsPanel() {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [names, setNames] = useState<KnownName[]>([]);
  const [editing, setEditing] = useState<string | null>(null); // a Primary Name, or '' for a new group
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/finance/client-groups');
      if (!res.ok) return;
      const body = (await res.json()) as { groups?: Group[] };
      if (Array.isArray(body.groups)) setGroups(body.groups);
      const nres = await authFetch('/api/v1/finance/client-names');
      if (nres.ok) setNames(((await nres.json()) as { names?: KnownName[] }).names ?? []);
    } catch {
      /* shows nothing */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const send = async (rows: { name: string; primary: string }[]) => {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const res = await authFetch('/api/v1/finance/client-groups/import', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows }) });
      if (!res.ok) return setProblem(res.status === 403 ? 'You can read this but not change it.' : `That was not saved (${res.status}).`);
      const out = (await res.json()) as { saved: number; removed: number };
      setNote(`${out.saved} name${out.saved === 1 ? '' : 's'} filed${out.removed ? `, ${out.removed} taken out of their group` : ''}.`);
      setEditing(null);
      await load();
    } catch {
      setProblem('That could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  if (groups === null) return null;
  return (
    <section className="space-y-2" data-testid="client-groups">
      <h2 className="text-sm font-semibold text-gray-200">Client groups</h2>
      <p className="text-xs text-gray-500">
        Client names filed under one Primary Name are one client on Net income: their revenue, hours and costs are added together, whether the name comes from HaloPSA or from QuickBooks. Use Edit to tick the names that belong to a group, or New group to make one.
      </p>
      {problem ? <p className="text-sm text-red-300" role="alert">{problem}</p> : null}
      {note ? <p className="text-sm text-emerald-300" data-testid="groups-note">{note}</p> : null}
      {groups.length === 0 ? <p className="text-xs text-gray-500">No client is filed under another name yet.</p> : null}
      <ul className="space-y-1 text-sm text-gray-200">
        {groups.map((g) => (
          <li key={g.primary} data-testid="group">
            <span className="font-medium">{g.primary}</span> <span className="text-xs text-gray-400">({g.members.join('; ')})</span>
            <button type="button" className={`${ghost} ml-2`} disabled={busy} onClick={() => setEditing(editing === g.primary ? null : g.primary)} aria-label={`Edit ${g.primary}`}>
              Edit
            </button>
            <button type="button" className={`${ghost} ml-1`} disabled={busy} onClick={() => void send(g.members.map((name) => ({ name, primary: '' })))} aria-label={`Take the names out of ${g.primary}`}>
              Ungroup
            </button>
            {editing === g.primary ? <Picker original={g} names={names} busy={busy} onSave={(rows) => void send(rows)} onCancel={() => setEditing(null)} /> : null}
          </li>
        ))}
      </ul>
      {editing === '' ? (
        <Picker original={null} names={names} busy={busy} onSave={(rows) => void send(rows)} onCancel={() => setEditing(null)} />
      ) : (
        <button type="button" className={ghost} disabled={busy} onClick={() => setEditing('')}>
          New group
        </button>
      )}
    </section>
  );
}
