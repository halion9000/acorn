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

export type StatusKey = 'overdue' | 'open' | 'done' | 'none' | 'offboarded';
const STATUS: Record<StatusKey, { label: string; tone: string; rank: number }> = {
  overdue: { label: 'Overdue tasks', tone: 'bg-red-500/15 text-red-300', rank: 0 },
  open: { label: 'Tasks in progress', tone: 'bg-amber-500/15 text-amber-300', rank: 1 },
  none: { label: 'No checklist started', tone: 'bg-gray-700/40 text-gray-300', rank: 2 },
  done: { label: 'All tasks completed', tone: 'bg-emerald-500/15 text-emerald-300', rank: 3 },
  offboarded: { label: 'Offboarded', tone: 'bg-gray-800 text-gray-400', rank: 4 },
};

/** One status for a person, the way Secureframe's People list shows it: offboarded, overdue tasks, tasks in progress, all tasks completed, or no checklist started (pure). */
export function personStatus(p: Pick<Person, 'active' | 'onboarding' | 'offboarding'>): { key: StatusKey; label: string; tone: string } {
  const lists = [p.onboarding, p.offboarding].filter((l) => l.started);
  const key: StatusKey = !p.active ? 'offboarded' : lists.some((l) => l.overdue > 0) ? 'overdue' : lists.some((l) => l.open > 0) ? 'open' : lists.length === 0 ? 'none' : 'done';
  return { key, label: STATUS[key].label, tone: STATUS[key].tone };
}

/** The people to show: the Active or Inactive tab, a status, and a search of name and address; overdue first, then by name (pure). */
export function visiblePeople(people: Person[], opts: { tab: 'active' | 'inactive'; status: StatusKey | ''; query: string }): Person[] {
  const needle = opts.query.trim().toLowerCase();
  return people
    .filter((p) => (opts.tab === 'active') === p.active)
    .filter((p) => !opts.status || personStatus(p).key === opts.status)
    .filter((p) => !needle || `${p.name ?? ''} ${p.email}`.toLowerCase().includes(needle))
    .sort((a, b) => STATUS[personStatus(a).key].rank - STATUS[personStatus(b).key].rank || (a.name ?? a.email).localeCompare(b.name ?? b.email, undefined, { sensitivity: 'base' }));
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
  const [tab, setTab] = useState<'active' | 'inactive'>('active');
  const [statusFilter, setStatusFilter] = useState<StatusKey | ''>('');
  const [query, setQuery] = useState('');

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
      {people && people.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="people-filters">
          {(['active', 'inactive'] as const).map((t) => (
            <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)} className={`rounded px-2 py-1 ${tab === t ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
              {t === 'active' ? 'Active' : 'Inactive'} ({people.filter((p) => p.active === (t === 'active')).length})
            </button>
          ))}
          <select aria-label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusKey | '')} className={input}>
            <option value="">Any status</option>
            {(Object.keys(STATUS) as StatusKey[]).map((k) => (
              <option key={k} value={k}>
                {STATUS[k].label}
              </option>
            ))}
          </select>
          <input aria-label="Search people" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or address" className={input} />
          <span className="text-xs text-gray-500" data-testid="people-overdue">
            {people.filter((p) => p.active && personStatus(p).key === 'overdue').length} with overdue tasks
          </span>
        </div>
      ) : null}
      <ul className="space-y-2">
        {visiblePeople(people ?? [], { tab, status: statusFilter, query }).map((p) => (
          <li key={p.email} className="rounded-lg border border-gray-800 bg-gray-900/50 p-3" data-testid="person">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-gray-100">
                  {p.name ?? p.email}
                  <span className={`ml-2 rounded px-1.5 py-0.5 text-xs font-normal ${personStatus(p).tone}`} data-testid="person-status">
                    {personStatus(p).label}
                  </span>
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
