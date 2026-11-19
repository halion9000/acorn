'use client';

/**
 * The auditor's pages: an outside auditor signs in and sees ONLY the audits that were opened to them: the requests (accept what staff provided, or send it back with a note) and the files (download, and add their own).
 * No sidebar, no staff pages; the server decides which audits they may open. A person who has not set up an authenticator app is asked to do that first.
 */
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';

import { AuditFiles } from '@/components/compliance/AuditFiles';
import { SetupAuthenticator } from '@/components/client-portal/ClientPortalView';
import { apiErrorDetail, auditPortalApi, authApi, type AuditDetail, type AuditRow } from '@/lib/api';
import { revokeServerSession } from '@/lib/auth-session';

const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';
const field = 'w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

/** What the server's refusal means for this page (pure): the authenticator app is missing, or the person is not an auditor sign-in at all. */
export function auditRefusal(status: number, detail: string): 'mfa' | 'not-auditor' | 'other' {
  if (status === 403 && detail.startsWith('mfa_setup_required')) return 'mfa';
  if (status === 403) return 'not-auditor';
  return 'other';
}

function Requests({ audit, onChange }: { audit: AuditDetail; onChange: (a: AuditDetail) => void }) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState('');
  const done = audit.status === 'complete';
  const act = async (id: string, body: { status?: 'open' | 'accepted'; note?: string }) => {
    setProblem('');
    try {
      onChange(await auditPortalApi.patchRequest(audit.id, id, body));
      setNotes((n) => ({ ...n, [id]: '' }));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'That did not work.');
    }
  };
  return (
    <div className="space-y-2" data-testid="portal-requests">
      <h4 className="text-sm font-semibold text-gray-200">Requests</h4>
      {problem && (
        <p role="alert" className="text-xs text-amber-300">
          {problem}
        </p>
      )}
      <ul className="space-y-2">
        {audit.items.map((r) => (
          <li key={r.id} className="rounded border border-gray-800 p-2 text-sm" data-testid="portal-request">
            <p className="text-gray-100">{r.title}</p>
            <p className="text-xs text-gray-400">
              {r.status}
              {r.owner ? ` · ${r.owner}` : ''}
              {r.due_date ? ` · due ${r.due_date}` : ''}
              {r.overdue ? ' · overdue' : ''}
            </p>
            {r.note && <p className="mt-1 whitespace-pre-line text-xs text-gray-300">{r.note}</p>}
            {r.link && (
              <a className="text-xs text-blue-300 hover:underline" href={r.link} target="_blank" rel="noreferrer noopener">
                Provided link
              </a>
            )}
            {!done && r.status !== 'open' && (
              <div className="mt-2 space-y-1">
                <input className={field} aria-label={`Note on ${r.title}`} placeholder="A note for the team (optional)" value={notes[r.id] ?? ''} onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
                <div className="flex gap-2">
                  {r.status === 'provided' && (
                    <button type="button" className={btn} aria-label={`Accept ${r.title}`} onClick={() => void act(r.id, { status: 'accepted', note: notes[r.id] })}>
                      Accept
                    </button>
                  )}
                  <button type="button" className={btn} aria-label={`Send back ${r.title}`} onClick={() => void act(r.id, { status: 'open', note: notes[r.id] })}>
                    Send back
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
        {audit.items.length === 0 && <li className="text-xs text-gray-500">No requests yet.</li>}
      </ul>
    </div>
  );
}

function AuditPage({ audit, onChange }: { audit: AuditDetail; onChange: (a: AuditDetail) => void }) {
  const id = audit.id;
  const load = useCallback(() => auditPortalApi.files(id), [id]);
  return (
    <section className="space-y-4 rounded-lg border border-gray-700 bg-gray-900/60 p-4" data-testid="portal-audit">
      <div>
        <h2 className="text-lg font-semibold text-white">{audit.name}</h2>
        <p className="text-xs text-gray-400">
          {audit.framework} · {audit.status}
          {audit.period_start || audit.period_end ? ` · ${audit.period_start ?? '?'} to ${audit.period_end ?? '?'}` : ''} · {audit.accepted} of {audit.requests} requests accepted
        </p>
      </div>
      <Requests audit={audit} onChange={onChange} />
      <AuditFiles locked={audit.status === 'complete'} load={load} upload={(body) => auditPortalApi.upload(id, body)} download={(f) => auditPortalApi.download(id, f.id)} />
    </section>
  );
}

export function AuditPortalView() {
  const router = useRouter();
  const [audits, setAudits] = useState<AuditRow[] | null>(null);
  const [open, setOpen] = useState<AuditDetail | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'mfa' | 'not-auditor' | 'other'>('loading');
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    try {
      const rows = await auditPortalApi.audits();
      setAudits(rows);
      setState('ok');
      if (rows.length === 1) setOpen(await auditPortalApi.get(rows[0]!.id));
    } catch (err) {
      const status = (err as { status?: number } | null)?.status ?? 0;
      const detail = apiErrorDetail(err) ?? (err instanceof Error ? err.message : 'Could not load.');
      setMessage(detail.replace(/^mfa_setup_required:\s*/, ''));
      setState(auditRefusal(status, detail));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const signOut = async () => {
    const server = await revokeServerSession();
    authApi.logout();
    router.replace('/login');
    if (!server.ended) toast.error('Signed out on this device, but the server could not end the session.');
  };

  return (
    <div className="mx-auto min-h-screen max-w-4xl bg-surface-base" data-testid="audit-portal">
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <p className="text-sm font-semibold text-white">Audit portal</p>
        <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800" onClick={() => void signOut()}>
          Sign out
        </button>
      </header>
      <main className="space-y-5 p-6">
        {state === 'loading' && (
          <p role="status" className="text-sm text-gray-500">
            Loading…
          </p>
        )}
        {state === 'mfa' && <SetupAuthenticator onDone={() => void load()} />}
        {state === 'not-auditor' && (
          <p role="alert" className="text-sm text-amber-300">
            This page is for auditor sign-ins. Staff use the console.
          </p>
        )}
        {state === 'other' && (
          <p role="alert" className="text-sm text-amber-300">
            {message}
          </p>
        )}
        {state === 'ok' && audits && (
          <>
            {audits.length === 0 && <p className="text-sm text-gray-400">No audit has been opened to you yet. Ask the team that invited you.</p>}
            {audits.length > 1 && (
              <ul className="space-y-1" data-testid="portal-audit-list">
                {audits.map((a) => (
                  <li key={a.id}>
                    <button type="button" className="text-left text-blue-300 hover:underline" onClick={() => void auditPortalApi.get(a.id).then(setOpen)}>
                      {a.name} <span className="text-xs text-gray-500">{a.framework} · {a.status}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {open && <AuditPage audit={open} onChange={setOpen} />}
          </>
        )}
      </main>
    </div>
  );
}
