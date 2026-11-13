'use client';

/**
 * Standing approvals ("always allow this kind of agent action, for this client or all, until this date") and the Undo list for what they approved on their own in the last 24 hours.
 * Only reversible kinds can be chosen; everything destructive still needs a person every time. Making or ending one is a person's act, which the server enforces.
 */
import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { apiErrorDetail, msspApi, standingApprovalsApi } from '@/lib/api';

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const DAY = 24 * 60 * 60 * 1000;

const words = (kind: string): string => kind.replace(/_/g, ' ');

export function StandingApprovals() {
  const list = useSWR('standing-approvals', () => standingApprovalsApi.list(), { revalidateOnFocus: false, shouldRetryOnError: false });
  const recent = useSWR('standing-approvals-recent', () => standingApprovalsApi.recentApproved(), { revalidateOnFocus: false, shouldRetryOnError: false });
  const [kind, setKind] = useState('');
  const clients = useSWR('standing-approvals-clients', () => msspApi.listChildren().catch(() => []), { revalidateOnFocus: false });
  // The clients ticked: none means every client; one or more makes one standing approval for each.
  const [picked, setPicked] = useState<string[]>([]);
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);

  const fail = (err: unknown, fallback: string) => toast.error(apiErrorDetail(err) ?? (err instanceof Error && err.message ? err.message : fallback));

  if (list.error) return <p className="mb-4 text-sm text-gray-500" data-testid="standing-error">The standing approvals could not be loaded.</p>;
  if (!list.data) return null;
  const data = list.data;
  const chosen = kind || data.allowed_types[0] || '';
  const now = Date.now();
  const undoable = (recent.data?.items ?? []).filter(
    (c) => c.standing_approval_id && !c.undone_at && c.undo && c.decided_at && now - Date.parse(c.decided_at) <= DAY,
  );

  const add = async () => {
    setBusy(true);
    try {
      if (picked.length === 0) {
        await standingApprovalsApi.create({ action_type: chosen, client_id: null, days });
        toast.success('Standing approval added');
      } else {
        const done = await standingApprovalsApi.createForClients({ action_type: chosen, client_ids: picked, days });
        const skipped = done.already_covered.length;
        toast.success(`${done.created.length} standing approval${done.created.length === 1 ? '' : 's'} added${skipped ? `; ${skipped} client${skipped === 1 ? ' was' : 's were'} already covered` : ''}`);
      }
      setPicked([]);
      await list.mutate();
    } catch (err) {
      fail(err, 'Could not add it.');
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id: string) => {
    setBusy(true);
    try {
      await standingApprovalsApi.revoke(id);
      await list.mutate();
    } catch (err) {
      fail(err, 'Could not revoke it.');
    } finally {
      setBusy(false);
    }
  };
  const undo = async (id: string) => {
    setBusy(true);
    try {
      await standingApprovalsApi.undo(id);
      toast.success('Undo requested');
      await recent.mutate();
    } catch (err) {
      fail(err, 'Could not undo it.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="standing">
      <h3 className="text-sm font-semibold text-gray-100">Standing approvals</h3>
      <p className="mt-1 text-xs text-gray-400">
        &quot;Always allow this kind of action&quot;, so you stop approving the same card every week. Only reversible kinds can be chosen ({data.allowed_types.map(words).join(', ')}). Deleting, disabling, isolating and blocking always ask a person.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-400">
          Kind of action
          <select className={`${input} mt-1 block`} value={chosen} onChange={(e) => setKind(e.target.value)}>
            {data.allowed_types.map((t) => (
              <option key={t} value={t}>{words(t)}</option>
            ))}
          </select>
        </label>
        <fieldset className="text-xs text-gray-400" data-testid="standing-clients">
          <legend>Clients (none ticked = all clients)</legend>
          <div className="mt-1 max-h-28 overflow-y-auto rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5">
            {(clients.data ?? []).length === 0 ? (
              <span className="text-gray-500">All clients</span>
            ) : (
              (clients.data ?? []).map((c) => (
                <label key={c.id} className="flex items-center gap-1.5 text-gray-200">
                  <input type="checkbox" checked={picked.includes(c.id)} onChange={() => setPicked((now) => (now.includes(c.id) ? now.filter((x) => x !== c.id) : [...now, c.id]))} />
                  {c.name}
                </label>
              ))
            )}
          </div>
        </fieldset>
        <label className="text-xs text-gray-400">
          Days
          <input type="number" min={1} max={365} className={`${input} mt-1 block w-20`} value={days} onChange={(e) => setDays(Math.max(1, Math.min(365, Number(e.target.value) || data.default_days)))} />
        </label>
        <button type="button" className={ghost} disabled={busy || !chosen} onClick={() => void add()}>Add standing approval</button>
      </div>
      {data.items.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500" data-testid="standing-empty">None yet. Every approval card still waits for a person.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-800 text-sm">
          {data.items.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 py-1.5" data-testid={`standing-${s.id}`}>
              <span className="text-gray-200">
                {words(s.action_type)} · {s.client_id ? `client ${s.client_id}` : 'all clients'} · until {s.expires_at.slice(0, 10)} · <span className={s.state === 'active' ? 'text-emerald-300' : 'text-gray-500'}>{s.state}</span>
              </span>
              {s.state === 'active' ? <button type="button" className={ghost} disabled={busy} onClick={() => void revoke(s.id)}>Revoke</button> : null}
            </li>
          ))}
        </ul>
      )}
      {undoable.length > 0 ? (
        <div className="mt-4" data-testid="undo-list">
          <h4 className="text-xs font-semibold text-gray-300">Approved on their own in the last 24 hours</h4>
          <ul className="mt-1 divide-y divide-gray-800 text-sm">
            {undoable.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-1.5">
                <span className="text-gray-200">{c.title}{c.undo?.how ? ` (undo: ${c.undo.how})` : ''}</span>
                <button type="button" className={ghost} disabled={busy} onClick={() => void undo(c.id)}>Undo</button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
