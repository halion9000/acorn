'use client';

/**
 * The security questionnaire of a vendor: make a one-time link (30 days unless set, no sign-in) for the vendor to answer 14 standard questions, copy it or e-mail it to the account manager,
 * and read the answers when they come back. An open link can be cancelled. Backed by /api/v1/compliance/vendors/{id}/questionnaires.
 */
import { useCallback, useEffect, useState } from 'react';

import { apiErrorDetail, vendorApi, type VendorQuestionnaire } from '@/lib/api';

/** "answered 2026-11-30 by Vera Vendor (vera@v.test)" / "open until 2026-12-21" / "expired 2026-12-21" (pure). */
export function questionnaireLine(q: Pick<VendorQuestionnaire, 'state' | 'expires_on' | 'respondent_name' | 'respondent_email' | 'answered_at'>): string {
  if (q.state === 'answered') return `answered ${(q.answered_at ?? '').slice(0, 10)} by ${q.respondent_name ?? 'the vendor'} (${q.respondent_email ?? 'no address'})`;
  if (q.state === 'open') return `open until ${q.expires_on}`;
  return `expired ${q.expires_on}`;
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const ANSWER: Record<string, string> = { yes: 'Yes', no: 'No', na: 'Not applicable' };

export function VendorQuestionnaires({ clientId, vendorId, archived, contactEmail }: { clientId: string; vendorId: string; archived: boolean; contactEmail: string | null }) {
  const [rows, setRows] = useState<VendorQuestionnaire[] | null>(null);
  const [fresh, setFresh] = useState<VendorQuestionnaire | null>(null);
  const [mail, setMail] = useState(false);
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await vendorApi.questionnaires(clientId, vendorId));
    } catch {
      setRows(null);
    }
  }, [clientId, vendorId]);
  useEffect(() => {
    void load();
  }, [load]);

  const make = async () => {
    setBusy(true);
    setProblem('');
    try {
      setFresh(await vendorApi.sendQuestionnaire(clientId, vendorId, { send: mail }));
      await load();
    } catch (x) {
      setProblem(apiErrorDetail(x) ?? 'The link could not be made.');
    }
    setBusy(false);
  };

  const cancel = async (id: string) => {
    setBusy(true);
    try {
      await vendorApi.cancelQuestionnaire(clientId, vendorId, id);
      await load();
    } catch (x) {
      setProblem(apiErrorDetail(x) ?? 'That link could not be cancelled.');
    }
    setBusy(false);
  };

  return (
    <div data-testid="vendor-questionnaires">
      <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">Security questionnaire</h4>
      <p className="text-xs text-gray-500">A link the vendor opens without signing in, answers once and sends back. It expires in 30 days.</p>
      {problem && (
        <p role="alert" className="mt-1 text-xs text-red-400">
          {problem}
        </p>
      )}
      {!archived && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button type="button" className={ghost} disabled={busy} onClick={() => void make()}>
            Make a questionnaire link
          </button>
          <label className="flex items-center gap-1 text-xs text-gray-300">
            <input type="checkbox" checked={mail} disabled={!contactEmail} onChange={(e) => setMail(e.target.checked)} /> E-mail it to {contactEmail ?? 'the account manager (add an address first)'}
          </label>
        </div>
      )}
      {fresh && (
        <p className="mt-2 text-xs text-emerald-300" aria-label="New link">
          <code className="break-all">{fresh.url ?? fresh.path}</code> {fresh.emailed ? '(e-mailed) ' : ''}
          <span className="text-gray-400">Copy it now; it cannot be shown again. A path with no address in front goes after your public address.</span>
        </p>
      )}
      {rows && rows.length > 0 && (
        <ul className="mt-2 space-y-2 text-xs" aria-label="Questionnaires sent">
          {rows.map((q) => (
            <li key={q.id} className="rounded border border-gray-800 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className={q.state === 'answered' ? 'text-emerald-300' : q.state === 'expired' ? 'text-gray-500' : 'text-gray-300'}>{questionnaireLine(q)}</span>
                {q.state === 'open' && (
                  <button type="button" className={ghost} disabled={busy} aria-label="Cancel this questionnaire link" onClick={() => void cancel(q.id)}>
                    Cancel
                  </button>
                )}
              </div>
              {q.answers.length > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-gray-400">Read the answers</summary>
                  <ul className="mt-1 space-y-1 text-gray-300">
                    {q.answers.map((a) => (
                      <li key={a.question}>
                        {a.question} <strong className={a.answer === 'no' ? 'text-amber-300' : 'text-gray-100'}>{ANSWER[a.answer] ?? a.answer}</strong>
                        {a.details ? <span className="text-gray-400"> - {a.details}</span> : null}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
