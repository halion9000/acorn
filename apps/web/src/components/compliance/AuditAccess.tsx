'use client';

/**
 * Compliance > Audits > one audit: who outside may open it (an auditor sign-in limited to this audit) and the audit's files. Staff create the sign-in here (a temporary password is shown once; the auditor sets up
 * an authenticator app before the audit opens) and can take the access away.
 */
import { useCallback, useEffect, useState } from 'react';

import { AuditFiles } from '@/components/compliance/AuditFiles';
import { apiErrorDetail, auditAccessApi, type AuditorRow } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const btn = 'rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40';

export function AuditAccess({ clientId, auditId, complete }: { clientId: string; auditId: string; complete: boolean }) {
  const [auditors, setAuditors] = useState<AuditorRow[] | null>(null);
  const [form, setForm] = useState({ account: '', email: '', name: '' });
  const [password, setPassword] = useState<string | null>(null);
  const [problem, setProblem] = useState('');

  const load = useCallback(async () => {
    try {
      setAuditors(await auditAccessApi.auditors(clientId, auditId));
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not load the auditors.');
    }
  }, [clientId, auditId]);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<void>) => {
    setProblem('');
    try {
      await work();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'That did not work.'));
    }
  };

  const loadFiles = useCallback(() => auditAccessApi.files(clientId, auditId), [clientId, auditId]);

  return (
    <div className="space-y-4" data-testid="audit-access">
      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-gray-200">Auditor sign-in</h4>
        <p className="text-xs text-gray-400">
          An outside auditor gets their own sign-in that opens only this audit: its requests and files, where they can accept what was provided and add files. They set up an authenticator app first.
        </p>
        {auditors === null ? (
          <p className="text-xs text-gray-500">Loading…</p>
        ) : auditors.length === 0 ? (
          <p className="text-xs text-gray-500" data-testid="no-auditors">
            No auditor can open this audit yet.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {auditors.map((a) => (
              <li key={a.user_id} className="flex items-center justify-between gap-2 rounded border border-gray-800 px-2 py-1" data-testid="auditor">
                <span className="text-gray-200">
                  {a.name}{' '}
                  <span className="text-xs text-gray-500">
                    {a.email ?? 'no e-mail'} · since {a.since.slice(0, 10)}
                  </span>
                </span>
                <button type="button" className={btn} aria-label={`Remove access for ${a.name}`} onClick={() => void act(async () => setAuditors(await auditAccessApi.unlink(clientId, auditId, a.user_id)))}>
                  Remove access
                </button>
              </li>
            ))}
          </ul>
        )}
        {!complete && (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const out = await auditAccessApi.invite(clientId, auditId, { account_name: form.account.trim(), email: form.email.trim() || null, name: form.name.trim() || null });
                setAuditors(out.auditors);
                setPassword(out.temporary_password);
                setForm({ account: '', email: '', name: '' });
              });
            }}
          >
            <label className="text-xs text-gray-400">
              Account name
              <input className={`${field} mt-1 block`} value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
            </label>
            <label className="text-xs text-gray-400">
              Name (optional)
              <input className={`${field} mt-1 block`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="text-xs text-gray-400">
              E-mail (optional)
              <input className={`${field} mt-1 block`} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <button type="submit" className={btn} disabled={form.account.trim().length < 3}>
              Create the auditor sign-in
            </button>
          </form>
        )}
        {password && (
          <p className="rounded border border-amber-700 bg-amber-950/40 p-2 text-xs text-amber-200" data-testid="temp-password">
            Temporary password, shown once: <span className="font-mono text-amber-100">{password}</span>. Send it to the auditor by a different route than the account name.
          </p>
        )}
        {problem && (
          <p role="alert" className="text-xs text-amber-300">
            {problem}
          </p>
        )}
      </div>
      <AuditFiles
        locked={complete}
        load={loadFiles}
        upload={(body) => auditAccessApi.upload(clientId, auditId, body)}
        download={(f) => auditAccessApi.download(clientId, auditId, f.id)}
        remove={(f) => auditAccessApi.remove(clientId, auditId, f.id)}
      />
    </div>
  );
}
