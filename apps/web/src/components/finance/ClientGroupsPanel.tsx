'use client';

/**
 * Settings > Finance > Client groups: client names filed under one Primary Name. A client is sometimes billed or worked under more than one name (a company and a brand, a renamed company); Net income adds the names of a
 * group into one client. Paste lines of "name, Primary Name"; a name with no Primary Name, or the same as its own, is taken out of its group. Backed by /api/v1/finance/client-groups.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

export interface Group {
  primary: string;
  members: string[];
}

/** The name and Primary Name in pasted lines ("Talking Monkey, Inc., Asylum / Talking Monkey" is split at the LAST comma or at a tab or semicolon); blank lines and lines with no second part are skipped (pure). */
export function parseGroupLines(text: string): { name: string; primary: string }[] {
  const out: { name: string; primary: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const cut = line.includes('\t') ? line.lastIndexOf('\t') : line.includes(';') ? line.lastIndexOf(';') : line.lastIndexOf(',');
    if (cut <= 0) continue;
    const name = line.slice(0, cut).trim().replace(/^"|"$/g, '');
    const primary = line.slice(cut + 1).trim().replace(/^"|"$/g, '');
    if (name) out.push({ name, primary });
  }
  return out;
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';

export function ClientGroupsPanel() {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [paste, setPaste] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/finance/client-groups');
      if (!res.ok) return;
      const body = (await res.json()) as { groups?: Group[] };
      if (Array.isArray(body.groups)) setGroups(body.groups);
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
      setPaste('');
      await load();
    } catch {
      setProblem('That could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  if (groups === null) return null;
  const rows = parseGroupLines(paste);
  return (
    <section className="space-y-2" data-testid="client-groups">
      <h2 className="text-sm font-semibold text-gray-200">Client groups</h2>
      <p className="text-xs text-gray-500">
        Client names filed under one Primary Name are one client on Net income: their revenue, hours and costs are added together. Paste lines such as <span className="font-mono">Talking Monkey, Inc., Asylum / Talking Monkey</span>.
      </p>
      {problem ? <p className="text-sm text-red-300" role="alert">{problem}</p> : null}
      {note ? <p className="text-sm text-emerald-300" data-testid="groups-note">{note}</p> : null}
      {groups.length === 0 ? <p className="text-xs text-gray-500">No client is filed under another name yet.</p> : null}
      <ul className="space-y-1 text-sm text-gray-200">
        {groups.map((g) => (
          <li key={g.primary} data-testid="group">
            <span className="font-medium">{g.primary}</span> <span className="text-xs text-gray-400">({g.members.join('; ')})</span>
            <button type="button" className={`${ghost} ml-2`} disabled={busy} onClick={() => void send(g.members.map((name) => ({ name, primary: '' })))} aria-label={`Take the names out of ${g.primary}`}>
              Ungroup
            </button>
          </li>
        ))}
      </ul>
      <textarea className={`${input} block w-full max-w-2xl`} rows={4} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={'Talking Monkey, Inc., Asylum / Talking Monkey'} aria-label="Names to file under a Primary Name" />
      <button type="button" className={ghost} disabled={busy || rows.length === 0} onClick={() => void send(rows)}>
        File {rows.length || ''} names
      </button>
    </section>
  );
}
