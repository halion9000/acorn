'use client';

/** Settings, Announcements: post a short message that shows above every page for the team until its end day (or until removed), and remove one. At most five show at once. Needs the workspace manage permission to post or remove. */
import { useCallback, useEffect, useState } from 'react';
import { authFetch } from '@/lib/auth-session';

interface Row {
  id: string;
  message: string;
  tone: string;
  ends_on: string | null;
  created_by: string | null;
}

const field = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';

export function AnnouncementsView() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [message, setMessage] = useState('');
  const [tone, setTone] = useState<'info' | 'warning'>('info');
  const [endsOn, setEndsOn] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/announcements');
      setRows(res.ok ? ((await res.json()) as Row[]) : []);
    } catch {
      setRows([]);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const detail = async (res: Response): Promise<string> => {
    if (res.status === 403) return 'You need to be a workspace manager to post or remove announcements.';
    try {
      const body = (await res.json()) as { detail?: unknown };
      return typeof body.detail === 'string' ? body.detail : `The API answered ${res.status}`;
    } catch {
      return `The API answered ${res.status}`;
    }
  };
  const post = async () => {
    setBusy(true);
    setProblem('');
    try {
      const res = await authFetch('/api/v1/announcements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, tone, ends_on: endsOn || null }) });
      if (!res.ok) setProblem(await detail(res));
      else {
        setMessage('');
        setEndsOn('');
        await load();
      }
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    setBusy(true);
    setProblem('');
    try {
      const res = await authFetch(`/api/v1/announcements/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!res.ok) setProblem(await detail(res));
      else await load();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Announcements</h1>
        <p className="mt-1 text-sm text-gray-400">A short message shown above every page to everyone in your organization, until its end day or until you remove it. Up to five show at once. It is plain text.</p>
      </div>
      <form
        className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void post();
        }}
      >
        <textarea aria-label="Message" required maxLength={400} rows={2} placeholder="What the team should know" value={message} onChange={(e) => setMessage(e.target.value)} className={`${field} w-full`} />
        <div className="flex flex-wrap items-center gap-3 text-sm text-gray-300">
          <label className="flex items-center gap-1">
            Kind
            <select aria-label="Kind" className={field} value={tone} onChange={(e) => setTone(e.target.value as 'info' | 'warning')}>
              <option value="info">Information</option>
              <option value="warning">Warning</option>
            </select>
          </label>
          <label className="flex items-center gap-1">
            Show until
            <input aria-label="Show until" type="date" className={field} value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || message.trim() === ''} className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-40">
            Post
          </button>
        </div>
      </form>
      {problem && (
        <p role="alert" className="text-sm text-amber-300">
          {problem}
        </p>
      )}
      {rows === null ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400" data-testid="announcements-empty">
          Nothing is showing.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="announcement-list">
          {rows.map((r) => (
            <li key={r.id} className="flex items-start justify-between gap-3 rounded border border-gray-800 p-3 text-sm text-gray-200">
              <div>
                <p>{r.message}</p>
                <p className="mt-1 text-xs text-gray-500">
                  {r.tone === 'warning' ? 'Warning' : 'Information'} · {r.ends_on ? `until ${r.ends_on}` : 'no end day'}
                  {r.created_by ? ` · posted by ${r.created_by}` : ''}
                </p>
              </div>
              <button type="button" disabled={busy} onClick={() => void remove(r.id)} className="shrink-0 rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40" aria-label={`Remove: ${r.message.slice(0, 40)}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
