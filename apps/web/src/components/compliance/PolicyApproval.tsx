'use client';

/**
 * Approval of a policy version: ask another person to approve the newest version, see every request and what was decided (the approval record), and approve or reject a request addressed to you.
 * Backed by /api/v1/governance/{id}/approvals. Only the person named can decide, and a rejection needs a reason: the server enforces both and says so when a button is pressed by the wrong person.
 */
import { useCallback, useEffect, useState } from 'react';

export interface Approval {
  id: string;
  version: number;
  approver: string;
  requested_by: string;
  requested_at: string;
  note: string;
  decision: 'pending' | 'approved' | 'rejected';
  decided_by: string | null;
  decided_at: string | null;
  comment: string;
}

/** One line for a request, such as "Version 2: approved by bob@x.com on 2026-11-17" (pure). */
export function approvalLine(a: Approval): string {
  const day = (iso: string | null) => (iso ?? '').slice(0, 10);
  if (a.decision === 'approved') return `Version ${a.version}: approved by ${a.decided_by ?? a.approver} on ${day(a.decided_at)}`;
  if (a.decision === 'rejected') return `Version ${a.version}: rejected by ${a.decided_by ?? a.approver} on ${day(a.decided_at)}${a.comment ? `: ${a.comment}` : ''}`;
  return `Version ${a.version}: waiting for ${a.approver} (asked by ${a.requested_by} on ${day(a.requested_at)})`;
}

/** The words for the badge next to a version (pure). */
export function approvalBadge(status: string | undefined): string {
  return status === 'approved' ? 'Approved' : status === 'rejected' ? 'Rejected' : status === 'pending' ? 'Waiting for approval' : 'Not sent for approval';
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const TONE: Record<Approval['decision'], string> = { approved: 'text-emerald-300', rejected: 'text-red-300', pending: 'text-amber-300' };

export function PolicyApproval({ itemId, scoped, onChange }: { itemId: string; scoped: (url: string, init?: RequestInit) => Promise<Response>; onChange?: () => void }) {
  const [rows, setRows] = useState<Approval[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [approver, setApprover] = useState('');
  const [note, setNote] = useState('');
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await scoped(`/api/v1/governance/${itemId}/approvals`);
      if (res.ok) setRows((await res.json()) as Approval[]);
    } catch {
      /* shows nothing */
    }
  }, [scoped, itemId]);
  useEffect(() => {
    void load();
  }, [load]);

  const send = async (url: string, body: unknown): Promise<boolean> => {
    setBusy(true);
    setProblem(null);
    try {
      const res = await scoped(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) {
        let why = '';
        try {
          const j = (await res.json()) as { detail?: unknown };
          why = typeof j.detail === 'string' ? j.detail : '';
        } catch {
          /* no reason given */
        }
        setProblem(why || `That was not saved (${res.status}).`);
        return false;
      }
      return true;
    } catch {
      setProblem('That could not be sent.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 rounded border border-gray-700 bg-gray-950/60 p-3 text-xs text-gray-300" data-testid="policy-approval">
      <div className="font-semibold text-gray-100">Approval</div>
      {rows === null ? <p className="mt-1 text-gray-500">Loading…</p> : null}
      {rows?.length === 0 ? <p className="mt-1 text-gray-500">Nobody has been asked to approve this policy yet.</p> : null}
      <ul className="mt-1 space-y-2">
        {(rows ?? []).map((a) => (
          <li key={a.id}>
            <span className={TONE[a.decision]}>{approvalLine(a)}</span>
            {a.note ? <span className="text-gray-500"> · {a.note}</span> : null}
            {a.decision === 'pending' ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <input className={`${input} w-64`} placeholder="Reason (needed to reject)" value={reasons[a.id] ?? ''} onChange={(e) => setReasons({ ...reasons, [a.id]: e.target.value })} aria-label={`Reason for version ${a.version}`} />
                <button
                  type="button"
                  className={ghost}
                  disabled={busy}
                  onClick={() => void (async () => { if (await send(`/api/v1/governance/${itemId}/approvals/${a.id}/decision`, { decision: 'approved', comment: reasons[a.id] ?? '' })) { await load(); onChange?.(); } })()}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className={ghost}
                  disabled={busy}
                  onClick={() => void (async () => { if (await send(`/api/v1/governance/${itemId}/approvals/${a.id}/decision`, { decision: 'rejected', comment: reasons[a.id] ?? '' })) { await load(); onChange?.(); } })()}
                >
                  Reject
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input className={`${input} w-64`} placeholder="Approver's e-mail address" value={approver} onChange={(e) => setApprover(e.target.value)} aria-label="Approver's e-mail address" />
        <input className={`${input} w-64`} placeholder="Note for the approver (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note for the approver" />
        <button
          type="button"
          className={ghost}
          disabled={busy || !approver.includes('@')}
          onClick={() => void (async () => { if (await send(`/api/v1/governance/${itemId}/approvals`, { approver_email: approver.trim(), note })) { setApprover(''); setNote(''); await load(); onChange?.(); } })()}
        >
          Ask for approval of the newest version
        </button>
      </div>
      {problem ? <p className="mt-2 text-red-300" role="alert">{problem}</p> : null}
    </div>
  );
}
