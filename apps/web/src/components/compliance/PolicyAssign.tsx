'use client';

/**
 * Assign a policy to people: everyone active, or addresses you paste, with a due day (14 days from now when left empty). Each assigned person sees the policy under My policies, can accept it there and is
 * reminded by e-mail until they do. Lists who it is assigned to with whether each has accepted the newest version, and lets you take it off one person. Backed by /api/v1/governance/{id}/assignments.
 */
import { useCallback, useEffect, useState } from 'react';

import { parseEmails } from './PolicyAcceptance';

interface Assignment {
  email: string;
  name: string | null;
  due_on: string;
  assigned_by: string | null;
  state: 'accepted' | 'pending' | 'overdue' | string;
  reminders_sent: number;
  last_reminded_on: string | null;
}

/** "Ann (ann@x.com) · pending, due 2026-12-01, reminded 2 times" (pure). */
export function assignmentLine(a: Assignment): string {
  const who = a.name ? `${a.name} (${a.email})` : a.email;
  if (a.state === 'accepted') return `${who} · accepted`;
  const reminded = a.reminders_sent > 0 ? `, reminded ${a.reminders_sent} time${a.reminders_sent === 1 ? '' : 's'}` : ', not reminded yet';
  return `${who} · ${a.state}, due ${a.due_on}${reminded}`;
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function PolicyAssign({ itemId, scoped, onChange }: { itemId: string; scoped: (url: string, init?: RequestInit) => Promise<Response>; onChange?: () => void }) {
  const [rows, setRows] = useState<Assignment[] | null>(null);
  const [paste, setPaste] = useState('');
  const [due, setDue] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await scoped(`/api/v1/governance/${itemId}/assignments`);
    if (!res.ok) return setRows(null);
    setRows((await res.json()) as Assignment[]);
  }, [scoped, itemId]);
  useEffect(() => {
    void load();
  }, [load]);

  const send = async (body: { emails: string[]; everyone: boolean }) => {
    setBusy(true);
    setProblem('');
    const res = await scoped(`/api/v1/governance/${itemId}/assignments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, ...(due ? { due_on: due } : {}) }),
    });
    setBusy(false);
    if (!res.ok) {
      const err = (await res.json().catch(() => ({}))) as { detail?: string };
      return setProblem(typeof err.detail === 'string' ? err.detail : `That could not be assigned (${res.status}).`);
    }
    setRows((await res.json()) as Assignment[]);
    setPaste('');
    onChange?.();
  };

  const remove = async (email: string) => {
    setBusy(true);
    const res = await scoped(`/api/v1/governance/${itemId}/assignments/${encodeURIComponent(email)}`, { method: 'DELETE' });
    setBusy(false);
    if (!res.ok) return setProblem(`That could not be removed (${res.status}).`);
    await load();
    onChange?.();
  };

  const addresses = parseEmails(paste);
  return (
    <div className="mt-4 border-t border-gray-800 pt-3" data-testid="policy-assign">
      <h4 className="text-sm font-semibold text-white">Assign to people</h4>
      <p className="mt-1 text-xs text-gray-400">An assigned person sees this policy under My policies, can accept it there, and is e-mailed a reminder until they do.</p>
      {problem && (
        <p role="alert" className="mt-2 text-xs text-red-400">
          {problem}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-400">
          Due day
          <input type="date" aria-label="Due day" className="mt-1 block rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <button type="button" className={ghost} disabled={busy} onClick={() => void send({ emails: [], everyone: true })}>
          Assign to everyone
        </button>
      </div>
      <label className="mt-3 block text-xs text-gray-400">
        Or assign to these addresses (paste)
        <textarea aria-label="Addresses to assign" rows={2} className="mt-1 block w-full rounded border border-gray-700 bg-gray-900 p-2 text-sm text-gray-100" value={paste} onChange={(e) => setPaste(e.target.value)} />
      </label>
      <button type="button" className={`${ghost} mt-2`} disabled={busy || addresses.length === 0} onClick={() => void send({ emails: addresses, everyone: false })}>
        Assign {addresses.length || ''} {addresses.length === 1 ? 'person' : 'people'}
      </button>
      {rows && rows.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-800 text-xs" aria-label="Assigned people">
          {rows.map((a) => (
            <li key={a.email} className="flex items-center justify-between gap-2 py-1">
              <span className={a.state === 'overdue' ? 'text-red-300' : a.state === 'accepted' ? 'text-emerald-300' : 'text-gray-300'}>{assignmentLine(a)}</span>
              <button type="button" className={ghost} disabled={busy} aria-label={`Take the policy off ${a.email}`} onClick={() => void remove(a.email)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
