'use client';

/**
 * People: each active person (and anyone with a checklist, such as a leaver) with how their onboarding and offboarding stand. Open a person to start the built-in checklist, tick tasks off, add a task of your own or
 * remove one. Backed by /api/v1/personnel. Ticking records who and when; the tasks stay on file after they are done.
 */
import { useCallback, useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';

export interface Progress {
  started: boolean;
  total: number;
  done: number;
  open: number;
  overdue: number;
}
export interface Person {
  email: string;
  name: string | null;
  active: boolean;
  onboarding: Progress;
  offboarding: Progress;
}
export interface Task {
  id: string;
  email: string;
  kind: 'onboarding' | 'offboarding';
  title: string;
  due_on: string | null;
  done_at: string | null;
  done_by: string | null;
}

/** "3 of 7 done, 1 overdue", "Not started", or "All 7 done" for one checklist (pure). */
export function checklistSummary(p: Progress): string {
  if (!p.started) return 'Not started';
  if (p.open === 0) return `All ${p.total} done`;
  return `${p.done} of ${p.total} done${p.overdue > 0 ? `, ${p.overdue} overdue` : ''}`;
}

const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1.5 text-sm text-gray-100';
const KIND_LABEL = { onboarding: 'Onboarding', offboarding: 'Offboarding' } as const;

function withClient(url: string, clientId: string): string {
  return clientId ? `${url}${url.includes('?') ? '&' : '?'}client_id=${encodeURIComponent(clientId)}` : url;
}

export function PersonnelView() {
  const [clientId, setClientId] = useState('');
  const [people, setPeople] = useState<Person[] | null>(null);
  const [open, setOpen] = useState<{ email: string; tasks: Task[] } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState('');
  const [addKind, setAddKind] = useState<Task['kind']>('onboarding');

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const scoped = useCallback((url: string, init?: RequestInit) => authFetch(withClient(url, clientId), init), [clientId]);

  const load = useCallback(async () => {
    try {
      const res = await scoped('/api/v1/personnel');
      if (res.ok) setPeople((await res.json()) as Person[]);
      else setPeople([]);
    } catch {
      setPeople([]);
    }
  }, [scoped]);
  useEffect(() => {
    setPeople(null);
    setOpen(null);
    void load();
  }, [load]);

  const loadTasks = async (email: string) => {
    const res = await scoped(`/api/v1/personnel/${encodeURIComponent(email)}/tasks`);
    setOpen({ email, tasks: res.ok ? ((await res.json()) as Task[]) : [] });
  };
  const send = async (url: string, method: string, body?: unknown): Promise<boolean> => {
    setBusy(true);
    setProblem(null);
    try {
      const res = await scoped(url, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!res.ok) {
        let why = '';
        try {
          const j = (await res.json()) as { detail?: unknown };
          why = typeof j.detail === 'string' ? j.detail : '';
        } catch {
          /* none given */
        }
        setProblem(why || (res.status === 403 ? 'You can read this but not change it.' : `That was not saved (${res.status}).`));
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
  const refresh = async (email: string) => {
    await load();
    await loadTasks(email);
  };

  return (
    <div className="space-y-3 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">People</h1>
        <p className="mt-1 text-sm text-gray-400">
          Each active person with how their onboarding and offboarding checklists stand. Open a person to start a checklist and tick tasks off; who did each and when stays on file.
        </p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose people" />
        </div>
      </div>
      {problem ? <p className="text-sm text-red-300" role="alert">{problem}</p> : null}
      {people === null ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {people?.length === 0 ? <p className="text-sm text-gray-500">No people are listed for this organization yet.</p> : null}
      <ul className="space-y-2">
        {(people ?? []).map((p) => (
          <li key={p.email} className="rounded-lg border border-gray-800 bg-gray-900/50 p-3" data-testid="person">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-gray-100">
                  {p.name ?? p.email}
                  {!p.active ? <span className="ml-2 rounded bg-gray-800 px-1.5 py-0.5 text-xs font-normal text-gray-400">no longer active</span> : null}
                </div>
                <div className="text-xs text-gray-500">{p.name ? p.email : ''}</div>
              </div>
              <div className="text-xs text-gray-300">Onboarding: {checklistSummary(p.onboarding)}</div>
              <div className="text-xs text-gray-300">Offboarding: {checklistSummary(p.offboarding)}</div>
              <button type="button" className={ghost} onClick={() => (open?.email === p.email ? setOpen(null) : void loadTasks(p.email))}>
                {open?.email === p.email ? 'Close' : 'Open'}
              </button>
            </div>
            {open?.email === p.email ? (
              <div className="mt-3 border-t border-gray-800 pt-3" data-testid="checklists">
                {(['onboarding', 'offboarding'] as const).map((kind) => {
                  const tasks = open.tasks.filter((t) => t.kind === kind);
                  return (
                    <div key={kind} className="mb-3">
                      <div className="flex items-center gap-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">{KIND_LABEL[kind]}</div>
                        <button type="button" className={ghost} disabled={busy} onClick={() => void (async () => { if (await send(`/api/v1/personnel/${encodeURIComponent(p.email)}/tasks/start`, 'POST', { kind })) await refresh(p.email); })()}>
                          {tasks.length === 0 ? `Start ${kind}` : 'Add the tasks that are missing'}
                        </button>
                      </div>
                      {tasks.length === 0 ? <p className="mt-1 text-xs text-gray-500">No {kind} tasks yet.</p> : null}
                      <ul className="mt-1 space-y-1">
                        {tasks.map((t) => (
                          <li key={t.id} className="flex items-center gap-2 text-sm text-gray-200">
                            <input
                              type="checkbox"
                              checked={t.done_at !== null}
                              disabled={busy}
                              aria-label={t.title}
                              onChange={(e) => void (async () => { if (await send(`/api/v1/personnel/tasks/${t.id}/done`, 'POST', { done: e.target.checked })) await refresh(p.email); })()}
                            />
                            <span className={t.done_at ? 'text-gray-500 line-through' : ''}>{t.title}</span>
                            <span className="text-xs text-gray-500">{t.done_at ? `done by ${t.done_by ?? 'someone'} on ${t.done_at.slice(0, 10)}` : t.due_on ? `due ${t.due_on}` : ''}</span>
                            <button type="button" className="ml-auto text-xs text-gray-500 hover:text-red-300" disabled={busy} onClick={() => void (async () => { if (await send(`/api/v1/personnel/tasks/${t.id}`, 'DELETE')) await refresh(p.email); })()}>
                              Remove
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
                <div className="flex flex-wrap items-center gap-2">
                  <select className={input} value={addKind} onChange={(e) => setAddKind(e.target.value as Task['kind'])} aria-label="Checklist for the new task">
                    <option value="onboarding">Onboarding</option>
                    <option value="offboarding">Offboarding</option>
                  </select>
                  <input className={`${input} w-72`} placeholder="A task of your own" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="A task of your own" />
                  <button type="button" className={ghost} disabled={busy || title.trim().length < 3} onClick={() => void (async () => { if (await send(`/api/v1/personnel/${encodeURIComponent(p.email)}/tasks`, 'POST', { kind: addKind, title })) { setTitle(''); await refresh(p.email); } })()}>
                    Add task
                  </button>
                </div>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
