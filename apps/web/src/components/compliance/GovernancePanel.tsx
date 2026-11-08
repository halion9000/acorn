'use client';

/**
 * Compliance > Review calendar and policy library: things that must be looked at again on a schedule (policies, vendor reviews, evidence renewals) with an owner and a due date, soonest first, and the text of a
 * policy kept in numbered versions that are only ever added. Backed by /api/v1/governance. Without the permission, or on an older API, it shows nothing.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

export interface GovItem {
  id: string;
  kind: 'policy' | 'vendor' | 'evidence' | 'other';
  title: string;
  owner: string;
  notes: string;
  interval_days: number;
  next_due: string;
  last_reviewed_at: string | null;
  state: 'overdue' | 'due soon' | 'ok';
  days_until: number;
  versions: number;
}
interface Version {
  version: number;
  body: string;
  change_note: string;
  created_at: string;
}

const KIND: Record<GovItem['kind'], string> = { policy: 'Policy', vendor: 'Vendor review', evidence: 'Evidence', other: 'Other' };
const TONE: Record<GovItem['state'], string> = { overdue: 'text-red-300', 'due soon': 'text-amber-300', ok: 'text-emerald-300' };
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function dueText(i: Pick<GovItem, 'state' | 'days_until' | 'next_due'>): string {
  if (i.state === 'overdue') return `${-i.days_until} day${i.days_until === -1 ? '' : 's'} overdue (${i.next_due})`;
  return i.days_until === 0 ? 'due today' : `due in ${i.days_until} day${i.days_until === 1 ? '' : 's'} (${i.next_due})`;
}

export function GovernancePanel() {
  const [items, setItems] = useState<GovItem[] | null>(null);
  const [kind, setKind] = useState<GovItem['kind']>('policy');
  const [title, setTitle] = useState('');
  const [owner, setOwner] = useState('');
  const [days, setDays] = useState(365);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState<{ id: string; versions: Version[] } | null>(null);
  const [draft, setDraft] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/governance');
      if (!res.ok) return;
      const body = (await res.json()) as unknown;
      if (Array.isArray(body)) setItems(body as GovItem[]);
    } catch {
      /* shows nothing */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const send = async (url: string, method: string, body?: unknown): Promise<Response | null> => {
    setBusy(true);
    setProblem(null);
    try {
      const res = await authFetch(url, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!res.ok) {
        setProblem(res.status === 403 ? 'You can read this but not change it.' : `The change was not saved (${res.status}).`);
        return null;
      }
      return res;
    } catch {
      setProblem('The change could not be sent.');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const loadVersions = async (id: string) => {
    const res = await authFetch(`/api/v1/governance/${id}/versions`);
    setOpen({ id, versions: res.ok ? ((await res.json()) as Version[]) : [] });
    setDraft('');
  };
  const toggleVersions = async (id: string) => (open?.id === id ? setOpen(null) : loadVersions(id));

  if (!items) return null;
  return (
    <section className="mt-8 rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="governance">
      <h2 className="text-base font-semibold text-white">Review calendar and policies</h2>
      <p className="mt-1 text-sm text-gray-400">Things that must be looked at again on a schedule, soonest first. Press Reviewed when you have; the next date is today plus the interval. A policy keeps numbered versions of its text, which are never edited, only added.</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-400">
          Kind
          <select className={`${input} mt-1 block`} value={kind} onChange={(e) => setKind(e.target.value as GovItem['kind'])}>
            {Object.entries(KIND).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-400">
          Title
          <input className={`${input} mt-1 block w-64`} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          Owner
          <input className={`${input} mt-1 block w-40`} value={owner} onChange={(e) => setOwner(e.target.value)} />
        </label>
        <label className="text-xs text-gray-400">
          Every (days)
          <input type="number" min={1} max={1095} className={`${input} mt-1 block w-24`} value={days} onChange={(e) => setDays(Math.max(1, Math.min(1095, Number(e.target.value) || 365)))} />
        </label>
        <button
          type="button"
          className={ghost}
          disabled={busy || !title.trim()}
          onClick={() =>
            void (async () => {
              if (await send('/api/v1/governance', 'POST', { kind, title: title.trim(), owner: owner.trim(), interval_days: days })) {
                setTitle('');
                setOwner('');
                await load();
              }
            })()
          }
        >
          Add
        </button>
      </div>
      {problem ? <p className="mt-2 text-sm text-amber-300" data-testid="governance-problem">{problem}</p> : null}
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500" data-testid="governance-empty">Nothing on the calendar yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-gray-800 text-sm">
          {items.map((i) => (
            <li key={i.id} className="py-2" data-testid={`gov-${i.id}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-gray-200">
                  <span className="text-gray-500">{KIND[i.kind]}</span> · {i.title}{i.owner ? ` · ${i.owner}` : ''} · <span className={TONE[i.state]}>{dueText(i)}</span>
                  {i.last_reviewed_at ? <span className="text-gray-500"> · last reviewed {i.last_reviewed_at}</span> : null}
                </span>
                <span className="flex gap-2">
                  {i.kind === 'policy' ? <button type="button" className={ghost} onClick={() => void toggleVersions(i.id)}>Versions ({i.versions})</button> : null}
                  <button type="button" className={ghost} disabled={busy} onClick={() => void (async () => { if (await send(`/api/v1/governance/${i.id}/reviewed`, 'POST')) await load(); })()}>Reviewed</button>
                  <button type="button" className={ghost} disabled={busy} onClick={() => void (async () => { if (await send(`/api/v1/governance/${i.id}`, 'DELETE')) await load(); })()}>Archive</button>
                </span>
              </div>
              {open?.id === i.id ? (
                <div className="mt-2 rounded border border-gray-700 bg-gray-950/60 p-3" data-testid="gov-versions">
                  {open.versions.length === 0 ? <p className="text-xs text-gray-500">No text saved yet.</p> : null}
                  {open.versions.map((v) => (
                    <div key={v.version} className="mb-2 text-xs text-gray-300">
                      <div className="font-semibold text-gray-100">Version {v.version} · {v.created_at.slice(0, 10)}{v.change_note ? ` · ${v.change_note}` : ''}</div>
                      <pre className="mt-1 whitespace-pre-wrap font-sans">{v.body}</pre>
                    </div>
                  ))}
                  <textarea className={`${input} mt-2 block w-full`} rows={4} placeholder="Paste the new text of this policy" value={draft} onChange={(e) => setDraft(e.target.value)} />
                  <button
                    type="button"
                    className={`${ghost} mt-2`}
                    disabled={busy || !draft.trim()}
                    onClick={() =>
                      void (async () => {
                        if (await send(`/api/v1/governance/${i.id}/versions`, 'POST', { body: draft })) {
                          await load();
                          await loadVersions(i.id);
                        }
                      })()
                    }
                  >
                    Save as a new version
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
