'use client';

/**
 * Sales and Finance > Billing sync (the Rewst saas-billing app, rebuilt): each license-count difference, what HaloPSA bills a client for an invoice line against what the tools count. A person with the
 * billing role approves one or several and CORE sets the client's recurring invoice line in HaloPSA to the counted quantity: no second approval. Lines can be hidden and brought back; hiding changes nothing
 * in HaloPSA. Reading needs the billing view permission, approving and hiding need billing:push (the built-in Billing role has both).
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { PageHeader } from '@/components/ui/kit';

export interface SyncRow {
  client_id: string;
  client_name: string;
  invoice_item: string;
  billed: number;
  counted: number;
  difference: number;
  /** The tool counts added into the counted number. Absent from an older API. */
  parts?: { source: string; item: string; count: number }[];
  hidden: boolean;
  can_push: boolean;
  /** The HaloPSA license (subscription) behind the line; absent from an older API. */
  license_id?: number | null;
  /** linked: the license is on the invoice; not_linked: the license exists but is not on it; na: no license; unknown: CORE has not sent licenses yet. */
  link?: 'linked' | 'not_linked' | 'na' | 'unknown';
  push: { status: 'none' | 'pending' | 'claimed' | 'done' | 'failed'; quantity: number | null; message: string | null; by: string | null; at: string | null };
}
interface SyncData {
  generated_at: string;
  rows: SyncRow[];
  hidden: number;
  counts_read_at?: string | null;
}
interface Result {
  client_id: string;
  invoice_item: string;
  ok: boolean;
  detail: string;
}

export const rowKey = (r: { client_id: string; invoice_item: string }): string => `${r.client_id}|${r.invoice_item}`;
export const signed = (n: number): string => (n > 0 ? `+${n}` : String(n));
export type LinkFilter = '' | 'linked' | 'not_linked' | 'na';
/** The rows matching the organization text, the line chosen ('' = all) and the Linked choice ('' = all), in the order given (pure). A row CORE has not sent licenses for yet counts as none of the three. */
export function filterRows(rows: SyncRow[], text: string, item: string, link: LinkFilter = ''): SyncRow[] {
  const q = text.trim().toLowerCase();
  return rows.filter((r) => (q === '' || r.client_name.toLowerCase().includes(q)) && (item === '' || r.invoice_item === item) && (link === '' || r.link === link));
}
export type SortKey = 'client_name' | 'invoice_item' | 'billed' | 'counted' | 'difference' | 'size' | 'status' | 'license_id' | 'linked';
export type SortDir = 'asc' | 'desc';
const linkRank = (r: SyncRow): number => (r.link === 'linked' ? 0 : r.link === 'not_linked' ? 1 : r.link === 'na' ? 2 : 3);
const statusRank = (r: SyncRow): number => (!r.can_push ? 0 : r.push.status === 'failed' ? 1 : r.push.status === 'pending' || r.push.status === 'claimed' ? 2 : r.push.status === 'done' ? 3 : 4);
/** The rows ordered by one column (pure; the same order for equal values is the order given). Text sorts without regard to letter case, 'size' is the size of the difference whichever way it goes. */
export function sortRows(rows: SyncRow[], key: SortKey | null, dir: SortDir): SyncRow[] {
  if (key === null) return rows;
  const sign = dir === 'asc' ? 1 : -1;
  const value = (r: SyncRow): number | string =>
    key === 'client_name' ? r.client_name.toLowerCase() : key === 'invoice_item' ? r.invoice_item.toLowerCase() : key === 'size' ? Math.abs(r.difference) : key === 'status' ? statusRank(r) : key === 'linked' ? linkRank(r) : key === 'license_id' ? (r.license_id ?? Number.MAX_SAFE_INTEGER) : r[key];
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      const x = value(a.r);
      const y = value(b.r);
      const c = typeof x === 'string' && typeof y === 'string' ? x.localeCompare(y) : Number(x) - Number(y);
      return c * sign || a.i - b.i;
    })
    .map((x) => x.r);
}
/** What a click on a header does: a new column starts ascending (numbers: largest first), the same column flips (pure). */
export function nextSort(current: { key: SortKey | null; dir: SortDir }, key: SortKey): { key: SortKey | null; dir: SortDir } {
  if (current.key === key) return { key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
  return { key, dir: key === 'client_name' || key === 'invoice_item' || key === 'status' || key === 'linked' || key === 'license_id' ? 'asc' : 'desc' };
}
/** The Linked column's words and color for a row (pure): Linked, Not Linked, N/A; nothing before CORE has sent licenses. */
export function linkText(r: SyncRow): { label: string; tone: string } {
  if (r.link === 'linked') return { label: 'Linked', tone: 'text-emerald-300' };
  if (r.link === 'not_linked') return { label: 'Not Linked', tone: 'text-amber-300' };
  if (r.link === 'na') return { label: 'N/A', tone: 'text-gray-400' };
  return { label: '', tone: 'text-gray-500' };
}
/** The counted number written out: "ThreatMate Internal assets 0" for each part, or why there is none (pure). */
export function partsText(r: SyncRow): string {
  if (!r.parts || r.parts.length === 0) return 'No tool count is mapped to this invoice line.';
  return r.parts.map((p) => `${p.source} ${p.item}: ${p.count}`).join(' + ');
}

/** Whether a row can be approved right now: mapped to HaloPSA, not already waiting (pure). */
/** Whether any pushed line is still on its way to HaloPSA, so the page keeps asking for its state. */
export const anyWaiting = (rows: SyncRow[]): boolean => rows.some((r) => r.push.status === 'pending' || r.push.status === 'claimed');

/** What the Refresh data line says: nothing before the first press; while waiting, that CORE was asked and what the last counts were; once the counts are newer than the press, when they were read (pure). */
export function refreshText(pressedAt: number | null, countsAt: string | null | undefined, now: number, timedOut: boolean): string {
  if (pressedAt === null) return '';
  const read = countsAt ? new Date(countsAt) : null;
  if (read && read.getTime() >= pressedAt) return `Counts read again at ${read.toLocaleTimeString()}.`;
  if (timedOut) return 'CORE has not finished reading yet (it can take ten minutes or more). The page will show the new counts when you refresh again.';
  const secs = Math.max(0, Math.round((now - pressedAt) / 1000));
  return `Asked CORE to read every tool and HaloPSA again (${secs}s ago). Counts last read ${read ? read.toLocaleTimeString() : 'never'}. This takes a few minutes; the page updates by itself.`;
}

export const canApprove = (r: SyncRow): boolean => r.can_push && r.push.status !== 'pending' && r.push.status !== 'claimed';
/** How a push reads for people (pure). */
export function pushText(p: SyncRow['push']): string {
  if (p.status === 'none') return '';
  if (p.status === 'pending' || p.status === 'claimed') return `Waiting for CORE: set to ${p.quantity}`;
  if (p.status === 'done') return p.message ?? `Set to ${p.quantity}`;
  return `Failed: ${p.message ?? 'no reason given'}`;
}

const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const ghost = 'rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';

export function BillingSyncView() {
  const [problem, setProblem] = useState<string | null>(null);
  const [data, setData] = useState<SyncData | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [text, setText] = useState('');
  const [item, setItem] = useState('');
  const [linkChoice, setLinkChoice] = useState<LinkFilter>('');
  const [sort, setSort] = useState<{ key: SortKey | null; dir: SortDir }>({ key: null, dir: 'desc' });
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [pressedAt, setPressedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(async (hidden: boolean) => {
    setLoading(true);
    try {
      const res = await authFetch(`/api/v1/billing/sync${hidden ? '?show_hidden=true' : ''}`);
      if (res.status === 403) {
        setProblem('Billing sync needs the billing role. Ask the owner to give you the Billing role.');
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setData((await res.json()) as SyncData);
      setProblem(null);
      setLoadedAt(new Date());
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load(showHidden);
  }, [load, showHidden]);
  // After Refresh data CORE reads every tool and HaloPSA again (a few minutes): ask for the list every eight seconds until the counts are newer than the press, for at most ten minutes.
  const countsNewer = pressedAt !== null && data?.counts_read_at ? new Date(data.counts_read_at).getTime() >= pressedAt : false;
  const timedOut = pressedAt !== null && Date.now() - pressedAt > 10 * 60 * 1000;
  const watching = pressedAt !== null && !countsNewer && !timedOut;
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => {
      setTick((n) => n + 1);
      void load(showHidden);
    }, 8000);
    return () => clearInterval(timer);
  }, [watching, load, showHidden]);
  const refresh = async (): Promise<void> => {
    const at = Date.now();
    setLoading(true);
    try {
      const res = await authFetch('/api/v1/billing/sync/refresh', { method: 'POST' });
      if (res.ok) setPressedAt(at);
    } catch {
      /* the list below is still read again */
    }
    await load(showHidden);
  };
  // CORE answers a push in about twenty seconds; until it has, ask again every five so the line changes by itself.
  const waiting = anyWaiting(data?.rows ?? []);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void load(showHidden), 5000);
    return () => clearInterval(timer);
  }, [waiting, load, showHidden]);

  const items = useMemo(() => [...new Set((data?.rows ?? []).map((r) => r.invoice_item))].sort(), [data]);
  const rows = useMemo(() => sortRows(filterRows(data?.rows ?? [], text, item, linkChoice), sort.key, sort.dir), [data, text, item, linkChoice, sort]);
  const chosen = rows.filter((r) => picked.has(rowKey(r)));
  const allPicked = rows.length > 0 && chosen.length === rows.length;

  const post = async (path: string, body: unknown): Promise<unknown> => {
    setBusy(true);
    try {
      const res = await authFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res.status === 403) throw new Error('You need the billing role to approve or hide lines.');
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      return await res.json();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not save');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const approve = async (list: SyncRow[]) => {
    const out = (await post("/api/v1/billing/sync/approve", { items: list.map((r) => ({ client_id: r.client_id, invoice_item: r.invoice_item })) })) as Result[] | null;
    if (out) {
      setResults(out);
      setPicked(new Set());
      await load(showHidden);
    }
  };
  const hide = async (list: SyncRow[], hidden: boolean) => {
    if ((await post("/api/v1/billing/sync/hide", { items: list.map((r) => ({ client_id: r.client_id, invoice_item: r.invoice_item })), hidden })) !== null) {
      setPicked(new Set());
      await load(showHidden);
    }
  };
  const toggle = (r: SyncRow) => {
    const next = new Set(picked);
    if (next.has(rowKey(r))) next.delete(rowKey(r));
    else next.add(rowKey(r));
    setPicked(next);
  };

  return (
    <div className="space-y-4 p-6">
      <PageHeader title="Billing sync" subtitle="Where what HaloPSA bills a client and what the tools count disagree. Approve a line and CORE sets the client&apos;s recurring invoice in HaloPSA to the counted number. Hiding a line changes nothing in HaloPSA." />
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Organization" className={input} placeholder="Filter by organization" value={text} onChange={(e) => setText(e.target.value)} />
        <select aria-label="Type" className={input} value={item} onChange={(e) => setItem(e.target.value)}>
          <option value="">All types</option>
          {items.map((i) => (
            <option key={i} value={i}>
              {i}
            </option>
          ))}
        </select>
        <select aria-label="Linked" className={input} value={linkChoice} onChange={(e) => setLinkChoice(e.target.value as LinkFilter)}>
          <option value="">Linked: all</option>
          <option value="linked">Linked</option>
          <option value="not_linked">Not Linked</option>
          <option value="na">N/A</option>
        </select>
        <label className="flex items-center gap-1 text-sm text-gray-300">
          <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} /> Show hidden{data && data.hidden > 0 ? ` (${data.hidden})` : ''}
        </label>
        <button type="button" className={ghost} disabled={busy || loading || watching} aria-busy={loading || watching} onClick={() => void refresh()}>
          {loading || watching ? 'Refreshing…' : 'Refresh data'}
        </button>
        <span className="text-xs text-gray-400" role="status" data-testid="billing-updated">
          {loading ? 'Reading the latest from A.C.O.R.N…' : loadedAt ? `Updated ${loadedAt.toLocaleTimeString()}` : ''}
        </span>
        <span className="text-xs text-sky-300" role="status" data-testid="billing-refresh" data-tick={tick}>
          {refreshText(pressedAt, data?.counts_read_at, Date.now(), timedOut)}
        </span>
        <button type="button" className={ghost} disabled={busy || rows.length === 0} onClick={() => setPicked(allPicked ? new Set() : new Set(rows.map(rowKey)))}>
          {allPicked ? 'Clear selection' : `Select all (${rows.length})`}
        </button>
        <button type="button" className={ghost} disabled={busy || chosen.filter(canApprove).length === 0} onClick={() => void approve(chosen.filter(canApprove))}>
          Approve selected ({chosen.filter(canApprove).length})
        </button>
        <button type="button" className={ghost} disabled={busy || chosen.length === 0} onClick={() => void hide(chosen, !chosen.every((r) => r.hidden))}>
          {chosen.length > 0 && chosen.every((r) => r.hidden) ? 'Unhide selected' : 'Hide selected'}
        </button>
      </div>
      {results.length > 0 && (
        <ul className="space-y-0.5 text-xs" data-testid="sync-results">
          {results.map((r) => (
            <li key={rowKey(r)} className={r.ok ? 'text-emerald-300' : 'text-amber-300'}>
              {r.invoice_item}: {r.detail}
            </li>
          ))}
        </ul>
      )}
      {data && data.rows.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="sync-empty">
          Nothing differs right now: every mapped line matches what is counted.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="sync-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2" />
                {(
                  [
                    ['client_name', 'Organization', ''],
                    ['invoice_item', 'Type', ''],
                    ['billed', 'Halo', 'text-right'],
                    ['counted', 'Tool Count', 'text-right'],
                    ['difference', 'Difference', 'text-right'],
                  ] as [SortKey, string, string][]
                ).map(([key, label, align]) => (
                  <th key={key} scope="col" className={`px-3 py-2 ${align}`} aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" className="uppercase hover:text-gray-300" onClick={() => setSort(nextSort(sort, key))} aria-label={`Sort by ${label}`}>
                      {label}
                      {sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  </th>
                ))}
                {(
                  [
                    ['license_id', 'License ID'],
                    ['linked', 'Linked'],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th key={key} scope="col" className="px-3 py-2" aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" className="uppercase hover:text-gray-300" onClick={() => setSort(nextSort(sort, key))} aria-label={`Sort by ${label}`}>
                      {label}
                      {sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  </th>
                ))}
                <th scope="col" className="px-3 py-2" aria-sort={sort.key === 'status' ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" className="uppercase hover:text-gray-300" onClick={() => setSort(nextSort(sort, 'status'))} aria-label="Sort by Status">
                    Status{sort.key === 'status' ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </button>
                </th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {rows.map((r) => (
                <Fragment key={rowKey(r)}>
                <tr className={r.hidden ? 'opacity-60' : ''}>
                  <td className="px-3 py-1.5">
                    <input type="checkbox" aria-label={`Select ${r.client_name} ${r.invoice_item}`} checked={picked.has(rowKey(r))} onChange={() => toggle(r)} />
                  </td>
                  <td className="px-3 py-1.5">{r.client_name}</td>
                  <td className="px-3 py-1.5">{r.invoice_item}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.billed}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    <button type="button" className="underline decoration-dotted hover:text-white" aria-expanded={open === rowKey(r)} aria-label={`Where the counted number of ${r.client_name} ${r.invoice_item} comes from`} onClick={() => setOpen(open === rowKey(r) ? null : rowKey(r))}>
                      {r.counted}
                    </button>
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${r.difference > 0 ? 'text-amber-300' : 'text-sky-300'}`}>{signed(r.difference)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-gray-300" data-testid="license-id">{r.license_id ?? (r.link && r.link !== 'unknown' ? 'None' : '')}</td>
                  <td className={`px-3 py-1.5 ${linkText(r).tone}`} data-testid="link">{linkText(r).label}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-400">
                    {!r.can_push ? 'Not mapped to HaloPSA' : pushText(r.push)}
                    {r.hidden ? ' (hidden)' : ''}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <button type="button" className={ghost} disabled={busy || !canApprove(r)} onClick={() => void approve([r])}>
                      Approve
                    </button>
                    <button type="button" className={`${ghost} ml-1`} disabled={busy} onClick={() => void hide([r], !r.hidden)}>
                      {r.hidden ? 'Unhide' : 'Hide'}
                    </button>
                  </td>
                </tr>
                {open === rowKey(r) && (
                  <tr data-testid="sync-detail" className="bg-gray-900/50">
                    <td />
                    <td colSpan={9} className="px-3 py-2 text-xs text-gray-300">
                      <p>
                        HaloPSA bills <span className="text-gray-100">{r.billed}</span> of <span className="text-gray-100">{r.invoice_item}</span>. A.C.O.R.N counts <span className="text-gray-100">{r.counted}</span> as: {partsText(r)}.
                      </p>
                      <p className="mt-1 text-gray-500">
                        If the tool count is not what this line is billed on (a line billed per user checked against assets, for example), change which counts it is checked against under{' '}
                        <a href="/settings/billing" className="text-blue-300 hover:underline">
                          Licenses &amp; Counts
                        </a>
                        .
                      </p>
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
