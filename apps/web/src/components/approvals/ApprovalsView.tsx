'use client';

/**
 * Approvals: the requests that wait for a person to decide (a Toolbox request, an agent's proposed action). Read from /api/v1/approvals; Approve and Deny use the decide route, which records who decided, when
 * and why. Approving a Toolbox request records the decision only: running it is a later stage.
 */
import { useCallback, useEffect, useState } from 'react';

import { PageHeader } from '@/components/ui/kit';
import { responderApi, type ApprovalRequest } from '@/lib/api';

export type Tab = 'pending' | 'approved' | 'denied' | 'expired';
const TABS: { id: Tab; label: string }[] = [
  { id: 'pending', label: 'Waiting' },
  { id: 'approved', label: 'Approved' },
  { id: 'denied', label: 'Denied' },
  { id: 'expired', label: 'Expired' },
];
const RISK_CLASS: Record<ApprovalRequest['risk_level'], string> = { low: 'text-emerald-300', medium: 'text-amber-300', high: 'text-red-300', critical: 'text-red-300' };

/** Who asked, in words: a Toolbox request names the technician, anything else its own requester (pure). */
export function requesterLabel(requestedBy: string): string {
  return requestedBy.startsWith('toolbox:') ? `Toolbox request from ${requestedBy.slice('toolbox:'.length)}` : requestedBy;
}

/** Whether approving this request only records the decision (a Toolbox request: nothing runs yet) (pure). */
export function recordsOnly(a: Pick<ApprovalRequest, 'action'>): boolean {
  return (a.action as { kind?: string } | null)?.kind === 'toolbox';
}

function Card({ item, onDecided }: { item: ApprovalRequest; onDecided: () => void }) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const decide = async (approve: boolean) => {
    if (!approve && !comment.trim()) {
      setProblem('Say why you are denying it.');
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (approve) await responderApi.approve(item.id, comment.trim() || undefined);
      else await responderApi.deny(item.id, comment.trim());
      onDecided();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'That was not saved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="space-y-2 rounded-xl border border-gray-800 bg-gray-900 p-4" data-testid="approval">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-sm font-semibold text-white">{item.title}</h2>
        <span className={`text-xs ${RISK_CLASS[item.risk_level]}`}>{item.risk_level} risk</span>
        <span className="text-xs text-gray-500">{requesterLabel(item.requested_by)}</span>
        <span className="text-xs text-gray-500">{new Date(item.created_at).toLocaleString()}</span>
      </div>
      <p className="whitespace-pre-line text-sm text-gray-300">{item.summary}</p>
      {item.status === 'pending' ? (
        <div className="space-y-2">
          {recordsOnly(item) ? <p className="text-xs text-gray-500">Approving records your decision. Nothing runs yet: running Toolbox requests is the next stage.</p> : null}
          {item.expires_at ? <p className="text-xs text-gray-500">Expires {new Date(item.expires_at).toLocaleDateString()}.</p> : null}
          <textarea aria-label="Comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (needed to deny)" className="block w-full max-w-md rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100" />
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={() => void decide(true)} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
              Approve
            </button>
            <button type="button" disabled={busy} onClick={() => void decide(false)} className="rounded-lg border border-red-500/60 px-3 py-1.5 text-sm text-red-300 disabled:opacity-50">
              Deny
            </button>
          </div>
          {problem ? (
            <p role="alert" className="text-sm text-red-300">
              {problem}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-gray-500">
          {item.status === 'approved' ? 'Approved' : item.status === 'denied' ? 'Denied' : 'Expired'}
          {item.decided_at ? ` ${new Date(item.decided_at).toLocaleString()}` : ''}
          {item.decision_comment ? `: ${item.decision_comment}` : ''}
        </p>
      )}
    </li>
  );
}

export function ApprovalsView() {
  const [tab, setTab] = useState<Tab>('pending');
  const [items, setItems] = useState<ApprovalRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (which: Tab) => {
    try {
      const res = await responderApi.listApprovals({ status: which, page_size: 100 });
      setItems(res.items);
      setError(null);
    } catch (e) {
      setItems([]);
      setError(e instanceof Error ? e.message : 'Could not load the approvals.');
    }
  }, []);

  useEffect(() => {
    void load(tab);
  }, [tab, load]);

  return (
    <div className="space-y-4 p-6" data-testid="approvals">
      <PageHeader title="Approvals" subtitle="Requests that wait for a person to decide, such as a Toolbox request. Your decision, your name and your comment are kept." />
      <div className="flex gap-2 text-sm">
        {TABS.map((t) => (
          <button key={t.id} type="button" aria-pressed={tab === t.id} onClick={() => { setItems(null); setTab(t.id); }} className={`rounded px-2 py-1 ${tab === t.id ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      {items === null ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {items?.length === 0 && !error ? <p className="text-sm text-gray-500">{tab === 'pending' ? 'Nothing is waiting for a decision.' : 'Nothing here.'}</p> : null}
      <ul className="space-y-3">
        {(items ?? []).map((a) => (
          <Card key={a.id} item={a} onDecided={() => void load(tab)} />
        ))}
      </ul>
    </div>
  );
}

export default ApprovalsView;
