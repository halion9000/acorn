'use client';

/**
 * One-time acceptance links for outside people (contractors, vendors) who have no account: paste addresses, press Make links, copy each link (shown once; only a hash is kept) or tick "E-mail the links".
 * Each link works once, needs no sign-in and expires (14 days unless set). Lists the links made with whether each is open, used or expired, and lets you cancel an open one.
 * Backed by /api/v1/governance/{id}/accept-links.
 */
import { useCallback, useEffect, useState } from 'react';

import { parseEmails } from './PolicyAcceptance';

interface LinkRow {
  id: string;
  email: string;
  version: number;
  expires_on: string;
  state: 'open' | 'used' | 'expired' | string;
  path: string | null;
  url: string | null;
  emailed: boolean;
}

/** "ann@x.com · open until 2026-12-01 (version 3)" (pure). */
export function linkLine(l: Pick<LinkRow, 'email' | 'state' | 'expires_on' | 'version'>): string {
  const when = l.state === 'open' ? `open until ${l.expires_on}` : l.state === 'used' ? 'used' : `expired ${l.expires_on}`;
  return `${l.email} · ${when} (version ${l.version})`;
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function PolicyAcceptLinks({ itemId, scoped }: { itemId: string; scoped: (url: string, init?: RequestInit) => Promise<Response> }) {
  const [rows, setRows] = useState<LinkRow[] | null>(null);
  const [fresh, setFresh] = useState<LinkRow[]>([]);
  const [paste, setPaste] = useState('');
  const [days, setDays] = useState('14');
  const [mail, setMail] = useState(false);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await scoped(`/api/v1/governance/${itemId}/accept-links`);
    if (!res.ok) return setRows(null);
    setRows((await res.json()) as LinkRow[]);
  }, [scoped, itemId]);
  useEffect(() => {
    void load();
  }, [load]);

  const make = async () => {
    setBusy(true);
    setProblem('');
    const res = await scoped(`/api/v1/governance/${itemId}/accept-links`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emails: parseEmails(paste), expires_days: Number(days) || 14, send: mail }),
    });
    setBusy(false);
    if (!res.ok) {
      const err = (await res.json().catch(() => ({}))) as { detail?: string };
      return setProblem(typeof err.detail === 'string' ? err.detail : `The links could not be made (${res.status}).`);
    }
    setFresh((await res.json()) as LinkRow[]);
    setPaste('');
    await load();
  };

  const cancel = async (id: string) => {
    setBusy(true);
    const res = await scoped(`/api/v1/governance/${itemId}/accept-links/${id}`, { method: 'DELETE' });
    setBusy(false);
    if (!res.ok) return setProblem(`That link could not be cancelled (${res.status}).`);
    await load();
  };

  const addresses = parseEmails(paste);
  return (
    <div className="mt-4 border-t border-gray-800 pt-3" data-testid="policy-accept-links">
      <h4 className="text-sm font-semibold text-white">Links for people without an account</h4>
      <p className="mt-1 text-xs text-gray-400">Each link shows the newest text, works once, needs no sign-in and then records the acceptance under that address.</p>
      {problem && (
        <p role="alert" className="mt-2 text-xs text-red-400">
          {problem}
        </p>
      )}
      <label className="mt-2 block text-xs text-gray-400">
        Addresses (paste)
        <textarea aria-label="Addresses for links" rows={2} className="mt-1 block w-full rounded border border-gray-700 bg-gray-900 p-2 text-sm text-gray-100" value={paste} onChange={(e) => setPaste(e.target.value)} />
      </label>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-400">
          Valid for (days)
          <input aria-label="Valid for days" type="number" min={1} max={60} className="mt-1 block w-20 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" value={days} onChange={(e) => setDays(e.target.value)} />
        </label>
        <label className="flex items-center gap-1 text-xs text-gray-300">
          <input type="checkbox" checked={mail} onChange={(e) => setMail(e.target.checked)} /> E-mail the links
        </label>
        <button type="button" className={ghost} disabled={busy || addresses.length === 0} onClick={() => void make()}>
          Make {addresses.length || ''} {addresses.length === 1 ? 'link' : 'links'}
        </button>
      </div>
      {fresh.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-emerald-300" aria-label="New links">
          {fresh.map((l) => (
            <li key={l.id}>
              {l.email}: <code className="break-all">{l.url ?? l.path}</code> {l.emailed ? '(e-mailed)' : ''}
            </li>
          ))}
          <li className="text-gray-400">Copy these now; they cannot be shown again. A path with no address in front goes after your public address.</li>
        </ul>
      )}
      {rows && rows.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-800 text-xs" aria-label="Links made">
          {rows.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-2 py-1">
              <span className={l.state === 'used' ? 'text-emerald-300' : l.state === 'expired' ? 'text-gray-500' : 'text-gray-300'}>{linkLine(l)}</span>
              {l.state === 'open' && (
                <button type="button" className={ghost} disabled={busy} aria-label={`Cancel the link for ${l.email}`} onClick={() => void cancel(l.id)}>
                  Cancel
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
