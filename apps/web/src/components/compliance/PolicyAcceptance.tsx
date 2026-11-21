'use client';

/**
 * Who accepted the newest version of a policy, and who has not. People come from the organization's active people; a person is recorded one at a time (Accepted) or several at once from pasted e-mail addresses.
 * Backed by /api/v1/governance/{id}/acceptances. A newer version asks everyone again, so a person who accepted only an older version stays on the pending list with that version shown.
 */
import { useCallback, useEffect, useState } from 'react';

import { PolicyAcceptLinks } from './PolicyAcceptLinks';
import { PolicyAssign } from './PolicyAssign';

interface Accepted {
  email: string;
  name: string | null;
  version: number;
  accepted_on: string;
  recorded_by: string | null;
}
interface Pending {
  email: string;
  name: string | null;
  older_version: number | null;
}
export interface Acceptance {
  version: number | null;
  accepted: Accepted[];
  pending: Pending[];
  others: Accepted[];
  share: number | null;
}

/** "7 of 12 accepted version 2 (58%)" (pure). */
export function acceptanceSummary(a: Acceptance): string {
  const done = a.accepted.length;
  const total = done + a.pending.length;
  if (total === 0) return 'No active people are listed for this organization yet.';
  return `${done} of ${total} accepted version ${a.version} (${Math.round((a.share ?? 0) * 100)}%)`;
}

/** The e-mail addresses in pasted text, split on commas, semicolons, spaces and new lines, lower case, once each (pure). */
export function parseEmails(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((e) => e.trim().toLowerCase()).filter((e) => /^[^@\s]+@[^@\s]+$/.test(e)))];
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function PolicyAcceptance({ itemId, scoped }: { itemId: string; scoped: (url: string, init?: RequestInit) => Promise<Response> }) {
  const [data, setData] = useState<Acceptance | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [paste, setPaste] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await scoped(`/api/v1/governance/${itemId}/acceptances`);
    if (!res.ok) return setProblem(`Acceptance could not be loaded (${res.status}).`);
    setProblem(null);
    setData((await res.json()) as Acceptance);
  }, [scoped, itemId]);
  useEffect(() => {
    void load();
  }, [load]);

  const record = async (emails: string[]) => {
    if (emails.length === 0) return;
    setBusy(true);
    const res = await scoped(`/api/v1/governance/${itemId}/acceptances`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ emails }) });
    setBusy(false);
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      return setProblem(typeof body.detail === 'string' ? body.detail : `Could not record it (${res.status}).`);
    }
    setProblem(null);
    setPaste('');
    setData((await res.json()) as Acceptance);
  };

  if (!data) return problem ? <p role="alert" className="text-xs text-red-400">{problem}</p> : null;
  return (
    <div className="mt-2 rounded border border-gray-700 bg-gray-950/60 p-3" data-testid="policy-acceptance">
      {problem ? <p role="alert" className="mb-2 text-xs text-red-400">{problem}</p> : null}
      {data.version === null ? (
        <p className="text-xs text-gray-500">Save the text of the policy first; there is nothing to accept yet.</p>
      ) : (
        <>
          <p className="text-sm text-gray-200" data-testid="acceptance-summary">{acceptanceSummary(data)}</p>
          {data.pending.length > 0 ? (
            <ul className="mt-2 divide-y divide-gray-800 text-xs" aria-label="Not yet accepted">
              {data.pending.map((p) => (
                <li key={p.email} className="flex items-center justify-between gap-2 py-1">
                  <span className="text-gray-300">
                    {p.name ? `${p.name} · ` : ''}{p.email}
                    {p.older_version ? <span className="text-gray-500"> · accepted version {p.older_version} only</span> : null}
                  </span>
                  <button type="button" className={ghost} disabled={busy} aria-label={`Record that ${p.email} accepted`} onClick={() => void record([p.email])}>Accepted</button>
                </li>
              ))}
            </ul>
          ) : null}
          {data.accepted.length > 0 ? (
            <ul className="mt-2 text-xs text-gray-400" aria-label="Accepted">
              {data.accepted.map((a) => (
                <li key={a.email}>{a.name ? `${a.name} · ` : ''}{a.email} · {a.accepted_on}{a.recorded_by ? ` · recorded by ${a.recorded_by}` : ''}</li>
              ))}
            </ul>
          ) : null}
          {data.others.length > 0 ? (
            <p className="mt-2 text-xs text-gray-500">Also recorded, not in the people list: {data.others.map((o) => o.email).join(', ')}</p>
          ) : null}
          <label className="mt-3 block text-xs text-gray-400">
            Record several at once (paste e-mail addresses)
            <textarea className="mt-1 block w-full rounded border border-gray-700 bg-gray-900 p-2 text-sm text-gray-100" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)} />
          </label>
          <button type="button" className={`${ghost} mt-2`} disabled={busy || parseEmails(paste).length === 0} onClick={() => void record(parseEmails(paste))}>
            Record {parseEmails(paste).length || ''} accepted
          </button>
          <PolicyAssign itemId={itemId} scoped={scoped} onChange={() => void load()} />
          <PolicyAcceptLinks itemId={itemId} scoped={scoped} />
        </>
      )}
    </div>
  );
}
