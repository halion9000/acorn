'use client';

/**
 * Settings > Upcoming improvements: everything waiting to be built or fixed, tagged with who it waits on (can be done without you, needs your sign-off, needs you to do something), filtered by where it stands
 * (new, not started, in progress, completed). The priority of each item is set here and is the order the work is taken in.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { apiErrorDetail, roadmapApi, type Roadmap, type RoadmapItem } from '@/lib/api';

type StatusFilter = 'all' | RoadmapItem['status'];
type NeedsFilter = 'all' | RoadmapItem['needs'];

export const STATUS_LABEL: Record<RoadmapItem['status'], string> = { new: 'New', not_started: 'Not started', in_progress: 'In progress', completed: 'Completed' };
export const NEEDS_LABEL: Record<RoadmapItem['needs'], string> = { claude: 'Can do without you', signoff: 'Needs your sign-off', hal: 'Needs you to do something' };
const NEEDS_CLASS: Record<RoadmapItem['needs'], string> = {
  claude: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
  signoff: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  hal: 'border-red-500/40 bg-red-500/15 text-red-300',
};
const STATUS_CLASS: Record<RoadmapItem['status'], string> = {
  new: 'text-sky-300',
  not_started: 'text-gray-400',
  in_progress: 'text-blue-300',
  completed: 'text-emerald-300',
};
const select = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-100';

/** The items to show for the filters (pure): where it stands, who it waits on and the area ('' for every area). */
export function visibleItems(items: RoadmapItem[], status: StatusFilter, needs: NeedsFilter, area = ''): RoadmapItem[] {
  return items.filter((i) => (status === 'all' || i.status === status) && (needs === 'all' || i.needs === needs) && (area === '' || i.area === area));
}

/** How many items carry each tag and each area, over the items that match the status tab (pure), so a filter shows what choosing it would leave. */
export function tagCounts(items: RoadmapItem[], status: StatusFilter): { needs: Record<RoadmapItem['needs'], number>; areas: [string, number][] } {
  const inStatus = items.filter((i) => status === 'all' || i.status === status);
  const needs = { claude: 0, signoff: 0, hal: 0 };
  const areas = new Map<string, number>();
  for (const i of inStatus) {
    needs[i.needs] += 1;
    areas.set(i.area, (areas.get(i.area) ?? 0) + 1);
  }
  return { needs, areas: [...areas.entries()].sort((a, b) => a[0].localeCompare(b[0])) };
}

export type SortKey = 'order' | 'newest' | 'area';
/** The visible items in the chosen order (pure). 'order' is the server's: open work first, the most urgent first. */
export function sortedItems(items: RoadmapItem[], sort: SortKey): RoadmapItem[] {
  if (sort === 'newest') return [...items].sort((a, b) => b.created_at.localeCompare(a.created_at));
  if (sort === 'area') return [...items].sort((a, b) => a.area.localeCompare(b.area) || a.title.localeCompare(b.title));
  return items;
}

/** A day as people read it ("14 Nov 2026"), from an ISO timestamp (pure); empty when there is none. */
export function dayText(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

/** The line under an item: when it was added and, once it is done, when it was completed (pure). */
export function datesText(item: { created_at: string; completed_at: string | null; status: string }): string {
  const added = dayText(item.created_at);
  const done = item.status === 'completed' ? dayText(item.completed_at) : '';
  return [added ? `Added ${added}` : '', done ? `Completed ${done}` : ''].filter(Boolean).join(' · ');
}

/** Whether an item shows the Approve button (pure): it waits on sign-off and is not finished. */
export function canApproveItem(item: { needs: string; status: string }): boolean {
  return item.needs === 'signoff' && item.status !== 'completed';
}

function Row({ item, onSave, onRemove, onApprove }: { item: RoadmapItem; onSave: (id: string, body: Parameters<typeof roadmapApi.update>[1]) => Promise<void>; onRemove: (id: string) => Promise<void>; onApprove: (id: string) => Promise<void> }) {
  const done = item.status === 'completed';
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="space-y-1 rounded-lg border border-gray-800 bg-gray-900/40 p-3" data-testid={`item-${item.key ?? item.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={`font-medium ${done ? 'text-gray-400 line-through' : 'text-white'}`}>{item.title}</p>
          <p className="text-xs text-gray-500">
            {item.area}
            {item.completed_ref ? ` · ${item.completed_ref}` : ''}
          </p>
          <p className="text-xs text-gray-500" data-testid={`dates-${item.key ?? item.id}`}>
            {datesText(item)}
            {item.approved_at ? `${datesText(item) ? ' · ' : ''}Approved${item.approved_by ? ` by ${item.approved_by}` : ''} ${dayText(item.approved_at)}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded border px-1.5 py-0.5 text-xs ${NEEDS_CLASS[item.needs]}`}>{NEEDS_LABEL[item.needs]}</span>
          <span className={`text-xs ${STATUS_CLASS[item.status]}`}>{STATUS_LABEL[item.status]}</span>
          <label className="text-xs text-gray-400">
            <span className="sr-only">Priority of {item.title}</span>
            <select aria-label={`Priority of ${item.title}`} value={item.priority} onChange={(e) => void onSave(item.id, { priority: e.target.value as RoadmapItem['priority'] })} className={select}>
              <option value="high">High priority</option>
              <option value="normal">Normal</option>
              <option value="low">Low priority</option>
            </select>
          </label>
          {canApproveItem(item) ? (
            <button type="button" aria-label={`Approve ${item.title}`} onClick={() => void onApprove(item.id)} className="rounded bg-emerald-700 px-2 py-1 text-xs text-white hover:bg-emerald-600">
              Approve
            </button>
          ) : null}
          <button type="button" onClick={() => void onSave(item.id, { status: done ? 'not_started' : 'completed' })} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800">
            {done ? 'Reopen' : 'Mark complete'}
          </button>
          {confirming ? (
            <span className="flex items-center gap-1 text-xs text-gray-300">
              Remove this item?
              <button type="button" onClick={() => void onRemove(item.id)} className="rounded bg-red-700 px-2 py-1 text-white hover:bg-red-600">
                Yes, remove
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="rounded border border-gray-700 px-2 py-1 hover:bg-gray-800">
                Keep
              </button>
            </span>
          ) : (
            <button type="button" aria-label={`Remove ${item.title}`} onClick={() => setConfirming(true)} className="text-xs text-gray-500 hover:text-red-300">
              Remove
            </button>
          )}
        </div>
      </div>
      {item.detail && <p className="whitespace-pre-wrap text-sm text-gray-300">{item.detail}</p>}
      {item.note && <p className="text-xs text-amber-200/80">{item.note}</p>}
    </li>
  );
}

export function RoadmapView() {
  const [data, setData] = useState<Roadmap | null>(null);
  const [problem, setProblem] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [needs, setNeeds] = useState<NeedsFilter>('all');
  const [area, setArea] = useState('');
  const [sort, setSort] = useState<SortKey>('order');
  const [draft, setDraft] = useState({ title: '', detail: '' });
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await roadmapApi.list());
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the list.'));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (id: string, body: Parameters<typeof roadmapApi.update>[1]) => {
    try {
      await roadmapApi.update(id, body);
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not save that change.');
    }
  };
  const approve = async (id: string) => {
    try {
      await roadmapApi.approve(id);
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not approve that.');
    }
  };
  const remove = async (id: string) => {
    try {
      await roadmapApi.remove(id);
      await load();
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? 'Could not remove that.');
    }
  };
  const shown = useMemo(() => (data ? sortedItems(visibleItems(data.items, status, needs, area), sort) : []), [data, status, needs, area, sort]);
  const counts = useMemo(() => (data ? tagCounts(data.items, status) : null), [data, status]);
  const tab = (value: StatusFilter, label: string, n?: number) => (
    <button key={value} role="tab" aria-selected={status === value} type="button" onClick={() => setStatus(value)} className={`px-3 py-1.5 text-sm ${status === value ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-gray-200'}`}>
      {label}
      {n !== undefined ? ` (${n})` : ''}
    </button>
  );

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Upcoming improvements</h1>
        <p className="mt-1 text-sm text-gray-400">
          Everything waiting to be built or fixed. Set a priority on an item and the high ones are taken first. The tag says who it waits on. This list is kept up to date as work is done.
        </p>
      </div>
      <div role="tablist" className="flex flex-wrap items-center gap-1 border-b border-gray-800">
        {tab('all', 'All', data ? data.items.length : undefined)}
        {tab('new', STATUS_LABEL.new, data?.counts.new)}
        {tab('not_started', STATUS_LABEL.not_started, data?.counts.not_started)}
        {tab('in_progress', STATUS_LABEL.in_progress, data?.counts.in_progress)}
        {tab('completed', STATUS_LABEL.completed, data?.counts.completed)}
        <span className="flex-1" />
        <label className="pb-1 text-xs text-gray-400">
          Waiting on{' '}
          <select aria-label="Waiting on" value={needs} onChange={(e) => setNeeds(e.target.value as NeedsFilter)} className={select}>
            <option value="all">Anyone</option>
            <option value="claude">{NEEDS_LABEL.claude}{counts ? ` (${counts.needs.claude})` : ''}</option>
            <option value="signoff">{NEEDS_LABEL.signoff}{counts ? ` (${counts.needs.signoff})` : ''}</option>
            <option value="hal">{NEEDS_LABEL.hal}{counts ? ` (${counts.needs.hal})` : ''}</option>
          </select>
        </label>
        <label className="ml-2 pb-1 text-xs text-gray-400">
          Area{' '}
          <select aria-label="Area" value={area} onChange={(e) => setArea(e.target.value)} className={select}>
            <option value="">Every area</option>
            {(counts?.areas ?? []).map(([a, n]) => (
              <option key={a} value={a}>
                {a} ({n})
              </option>
            ))}
          </select>
        </label>
        <label className="ml-2 pb-1 text-xs text-gray-400">
          Sort{' '}
          <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className={select}>
            <option value="order">By urgency</option>
            <option value="newest">Newest first</option>
            <option value="area">By area</option>
          </select>
        </label>
        <button type="button" onClick={() => setAdding((a) => !a)} className="mb-1 ml-2 rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
          Add an item
        </button>
      </div>
      {adding && (
        <form
          className="space-y-2 rounded-lg border border-gray-700 bg-gray-900/60 p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await roadmapApi.add({ title: draft.title.trim(), detail: draft.detail });
              setDraft({ title: '', detail: '' });
              setAdding(false);
              await load();
            } catch (x) {
              setProblem(apiErrorDetail(x) ?? 'Could not add that.');
            }
          }}
        >
          <input aria-label="New item title" required minLength={3} placeholder="What should be built or fixed" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" />
          <textarea aria-label="New item details" rows={2} placeholder="Details (optional)" value={draft.detail} onChange={(e) => setDraft({ ...draft, detail: e.target.value })} className="block w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100" />
          <button type="submit" className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
            Save item
          </button>
        </form>
      )}
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && shown.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="roadmap-empty">
          Nothing here.
        </p>
      )}
      <ul className="space-y-2" data-testid="roadmap-list">
        {shown.map((i) => (
          <Row key={i.id} item={i} onSave={save} onRemove={remove} onApprove={approve} />
        ))}
      </ul>
    </div>
  );
}
