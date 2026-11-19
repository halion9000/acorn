'use client';

/**
 * My policies: the policies assigned to the signed-in person, each with its text, and a button to accept the newest version. What was accepted stays listed with the day. Backed by /api/v1/me/policies.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { PageHeader } from '@/components/ui/kit';

export interface MyPolicy {
  item_id: string;
  title: string;
  version: number;
  body: string;
  due_on: string;
  state: 'pending' | 'overdue' | 'accepted' | string;
  accepted_on: string | null;
}

/** The line under a policy's title: its version, and either when it was accepted or when it is due (pure). */
export function policyLine(p: MyPolicy): string {
  if (p.state === 'accepted') return `Version ${p.version} · accepted ${p.accepted_on ?? ''}`.trim();
  return `Version ${p.version} · due ${p.due_on}${p.state === 'overdue' ? ' (overdue)' : ''}`;
}

/** The policies still to accept come first, the overdue ones before the others, then by due day (pure). */
export function inOrder(all: MyPolicy[]): MyPolicy[] {
  const rank = (p: MyPolicy) => (p.state === 'overdue' ? 0 : p.state === 'pending' ? 1 : 2);
  return [...all].sort((a, b) => rank(a) - rank(b) || a.due_on.localeCompare(b.due_on) || a.title.localeCompare(b.title));
}

const btn = 'rounded bg-emerald-700 px-3 py-1.5 text-sm text-white hover:bg-emerald-600 disabled:opacity-40';

export function MyPoliciesView() {
  const [rows, setRows] = useState<MyPolicy[] | null>(null);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/me/policies');
      if (!res.ok) return setProblem(`Your policies could not be loaded (${res.status}).`);
      const body = (await res.json()) as { policies?: MyPolicy[] };
      setRows(Array.isArray(body.policies) ? body.policies : []);
      setProblem('');
    } catch {
      setProblem('Your policies could not be loaded.');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const accept = async (id: string) => {
    setBusy(id);
    try {
      const res = await authFetch(`/api/v1/me/policies/${encodeURIComponent(id)}/accept`, { method: 'POST' });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setProblem(typeof body.detail === 'string' ? body.detail : `That could not be recorded (${res.status}).`);
      } else {
        setProblem('');
        await load();
      }
    } catch {
      setProblem('That could not be recorded.');
    } finally {
      setBusy('');
    }
  };

  const todo = rows ? rows.filter((r) => r.state !== 'accepted').length : 0;
  return (
    <div className="space-y-4 p-6">
      <PageHeader title="My policies" subtitle="The policies your organization has asked you to read and accept. Read each one, then press Accept. Your acceptance is recorded with today's date." />
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {rows && rows.length === 0 && !problem && <p className="text-sm text-gray-400" data-testid="no-policies">Nothing has been assigned to you.</p>}
      {rows && rows.length > 0 && (
        <p className="text-sm text-gray-300" data-testid="policies-summary">
          {todo === 0 ? 'You have accepted everything assigned to you.' : `${todo} to read and accept.`}
        </p>
      )}
      <ul className="space-y-4">
        {inOrder(rows ?? []).map((p) => (
          <li key={p.item_id} className="rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="my-policy">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-white">{p.title}</h2>
                <p className={`text-xs ${p.state === 'overdue' ? 'text-red-300' : 'text-gray-400'}`}>{policyLine(p)}</p>
              </div>
              {p.state !== 'accepted' && (
                <button type="button" className={btn} disabled={busy === p.item_id} aria-label={`Accept ${p.title}`} onClick={() => void accept(p.item_id)}>
                  Accept
                </button>
              )}
            </div>
            <details className="mt-3" open={p.state !== 'accepted'}>
              <summary className="cursor-pointer text-xs text-gray-400">The policy</summary>
              <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded border border-gray-800 bg-gray-950/60 p-3 text-sm text-gray-200">{p.body}</pre>
            </details>
          </li>
        ))}
      </ul>
    </div>
  );
}
