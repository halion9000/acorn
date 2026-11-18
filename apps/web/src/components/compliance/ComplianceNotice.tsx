'use client';

/**
 * Compliance > Weekly notice: who is e-mailed the compliance action items once a week, and an optional web address that gets the same list as JSON. Nothing is sent when no item is waiting. Send now tries the setup straight away.
 * Backed by /api/v1/compliance/notices.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

export interface Notice {
  emails: string[];
  webhook_url: string | null;
  weekly: boolean;
  last_sent_at: string | null;
  last_result: string | null;
}

/** The e-mail addresses in pasted text, split on commas, semicolons, spaces and new lines, lower case, once each (pure). */
export function parseNoticeEmails(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((e) => e.trim().toLowerCase()).filter((e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)))];
}

/** When the notice last went and how, in one line (pure). */
export function lastLine(n: Notice): string {
  if (!n.last_result) return 'It has not been sent yet.';
  return `${n.last_sent_at ? `Last sent ${n.last_sent_at.slice(0, 10)}. ` : 'Not sent yet. '}${n.last_result}`;
}

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

function scoped(url: string, clientId: string): string {
  return clientId ? `${url}?client_id=${encodeURIComponent(clientId)}` : url;
}

export function ComplianceNotice({ clientId = '' }: { clientId?: string }) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [emails, setEmails] = useState('');
  const [url, setUrl] = useState('');
  const [weekly, setWeekly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(scoped('/api/v1/compliance/notices', clientId));
      if (!res.ok) return;
      const n = (await res.json()) as Notice;
      if (!n || !Array.isArray(n.emails)) return; // not the answer of this version of the server
      setNotice(n);
      setEmails(n.emails.join('\n'));
      setUrl(n.webhook_url ?? '');
      setWeekly(n.weekly);
    } catch {
      /* shows nothing */
    }
  }, [clientId]);
  useEffect(() => {
    setNotice(null);
    void load();
  }, [load]);

  const call = async (path: string, method: string, body?: unknown) => {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const res = await authFetch(scoped(path, clientId), { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!res.ok) {
        let why = '';
        try {
          const j = (await res.json()) as { detail?: unknown };
          why = typeof j.detail === 'string' ? j.detail : '';
        } catch {
          /* none given */
        }
        setProblem(why || (res.status === 403 ? 'You can read this but not change it.' : `That was not saved (${res.status}).`));
        return null;
      }
      return res;
    } catch {
      setProblem('That could not be sent.');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    const res = await call('/api/v1/compliance/notices', 'PUT', { emails: parseNoticeEmails(emails), webhook_url: url.trim() || null, weekly });
    if (res) {
      setNote('Saved.');
      await load();
    }
  };
  const sendNow = async () => {
    const res = await call('/api/v1/compliance/notices/send', 'POST');
    if (!res) return;
    const out = (await res.json()) as { sent: boolean; items: number; email: string; webhook: string };
    setNote(out.items === 0 ? 'Nothing is waiting, so nothing was sent.' : `${out.sent ? 'Sent' : 'Not sent'}: ${out.items} items. E-mail: ${out.email}. Web address: ${out.webhook}.`);
    await load();
  };

  if (notice === null) return null;
  return (
    <section className="mt-6 rounded-lg border border-gray-800 bg-gray-900/50 p-4" data-testid="compliance-notice">
      <h2 className="text-sm font-semibold text-gray-200">Weekly notice of action items</h2>
      <p className="mt-1 text-xs text-gray-500">The action items listed above, e-mailed once a week to the people below and sent as JSON to a web address if you give one. Nothing is sent when no item is waiting.</p>
      <label className="mt-3 block text-xs text-gray-400" htmlFor="notice-emails">E-mail addresses (one a line)</label>
      <textarea id="notice-emails" className={`${input} mt-1 block w-full max-w-xl`} rows={3} value={emails} onChange={(e) => setEmails(e.target.value)} />
      <label className="mt-3 block text-xs text-gray-400" htmlFor="notice-url">Web address (https), optional</label>
      <input id="notice-url" className={`${input} mt-1 block w-full max-w-xl`} placeholder="https://hooks.example.com/…" value={url} onChange={(e) => setUrl(e.target.value)} />
      <label className="mt-3 flex items-center gap-2 text-sm text-gray-200">
        <input type="checkbox" checked={weekly} onChange={(e) => setWeekly(e.target.checked)} />
        Send it every week
      </label>
      <div className="mt-3 flex gap-2">
        <button type="button" className={ghost} disabled={busy} onClick={() => void save()}>Save</button>
        <button type="button" className={ghost} disabled={busy || (notice.emails.length === 0 && !notice.webhook_url)} onClick={() => void sendNow()}>Send now</button>
      </div>
      {problem ? <p className="mt-2 text-sm text-red-300" role="alert">{problem}</p> : null}
      {note ? <p className="mt-2 text-sm text-emerald-300" data-testid="notice-note">{note}</p> : null}
      <p className="mt-2 text-xs text-gray-500" data-testid="notice-last">{lastLine(notice)}</p>
    </section>
  );
}
