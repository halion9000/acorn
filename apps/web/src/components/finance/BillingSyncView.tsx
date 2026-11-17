'use client';

/**
 * Sales and Finance > Billing sync (the Rewst saas-billing app, rebuilt): each license-count difference, what HaloPSA bills a client for an invoice line against what the tools count. A person with the
 * billing role approves one or several and CORE sets the client's recurring invoice line in HaloPSA to the counted quantity: no second approval. Lines can be hidden and brought back; hiding changes nothing
 * in HaloPSA. Reading needs the billing view permission, approving and hiding need billing:push (the built-in Billing role has both).
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

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
  push: { status: 'none' | 'pending' | 'claimed' | 'done' | 'failed'; quantity: number | null; message: string | null; by: string | null; at: string | null };
}
interface SyncData {
  generated_at: string;
  rows: SyncRow[];
  hidden: number;
}
interface Result {
  client_id: string;
  invoice_item: string;
  ok: boolean;
  detail: string;
}

export const rowKey = (r: { client_id: string; invoice_item: string }): string => `${r.client_id}|${r.invoice_item}`;
export const signed = (n: number): string => (n > 0 ? `+${n}` : String(n));
/** The rows matching the organization text and the line chosen ('' = all), in the order given (pure). */
export function filterRows(rows: SyncRow[], text: string, item: string): SyncRow[] {
  const q = text.trim().toLowerCase();
  return rows.filter((r) => (q === '' || r.client_name.toLowerCase().includes(q)) && (item === '' || r.invoice_item === item));
}
export type SortKey = 'client_name' | 'invoice_item' | 'billed' | 'counted' | 'difference' | 'size' | 'status';
export type SortDir = 'asc' | 'desc';
const statusRank = (r: SyncRow): number => (!r.can_push ? 0 : r.push.status === 'failed' ? 1 : r.push.status === 'pending' || r.push.status === 'claimed' ? 2 : r.push.status === 'done' ? 3 : 4);
/** The rows ordered by one column (pure; the same order for equal values is the order given). Text sorts without regard to letter case, 'size' is the size of the difference whichever way it goes. */
export function sortRows(rows: SyncRow[], key: SortKey | null, dir: SortDir): SyncRow[] {
  if (key === null) return rows;
  const sign = dir === 'asc' ? 1 : -1;
  const value = (r: SyncRow): number | string =>
    key === 'client_name' ? r.client_name.toLowerCase() : key === 'invoice_item' ? r.invoice_item.toLowerCase() : key === 'size' ? Math.abs(r.difference) : key === 'status' ? statusRank(r) : r[key];
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
  return { key, dir: key === 'client_name' || key === 'invoice_item' || key === 'status' ? 'asc' : 'desc' };
}
/** The counted number written out: "ThreatMate Internal assets 0" for each part, or why there is none (pure). */
export function partsText(r: SyncRow): string {
  if (!r.parts || r.parts.length === 0) return 'No tool count is mapped to this invoice line.';
  return r.parts.map((p) => `${p.source} ${p.item}: ${p.count}`).join(' + ');
}

/** Whether a row can be approved right now: mapped to HaloPSA, not already waiting (pure). */
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
  const [sort, setSort] = useState<{ key: SortKey | null; dir: SortDir }>({ key: null, dir: 'desc' });
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);

  const load = useCallback(async (hidden: boolean) => {
    try {
      const res = await authFetch(`/api/v1/billing/sync${hidden ? '?show_hidden=true' : ''}`);
      if (res.status === 403) {
        setProblem('Billing sync needs the billing role. Ask the owner to give you the Billing role.');
        return;
      }
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setData((await res.json()) as SyncData);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not load');
    }
  }, []);
  useEffect(() => {
    void load(showHidden);
  }, [load, showHidden]);

  const items = useMemo(() => [...new Set((data?.rows ?? []).map((r) => r.invoice_item))].sort(), [data]);
  const rows = useMemo(() => sortRows(filterRows(data?.rows ?? [], text, item), sort.key, sort.dir), [data, text, item, sort]);
  const chosen = rows.filter((r) => picked.has(rowKey(r)));

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
      <div>
        <h1 className="text-2xl font-bold text-white">Billing sync</h1>
        <p className="mt-1 text-sm text-gray-400">
          Where what HaloPSA bills a client and what the tools count disagree. Approve a line and CORE sets the client&apos;s recurring invoice in HaloPSA to the counted number. Hiding a line changes nothing in HaloPSA.
        </p>
      </div>
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
        <label className="flex items-center gap-1 text-sm text-gray-300">
          <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} /> Show hidden{data && data.hidden > 0 ? ` (${data.hidden})` : ''}
        </label>
        <button type="button" className={ghost} disabled={busy} onClick={() => void load(showHidden)}>
          Refresh data
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
                    ['billed', 'Billed', 'text-right'],
                    ['counted', 'Counted', 'text-right'],
                    ['difference', 'Difference', 'text-right'],
                    ['status', 'Status', ''],
                  ] as [SortKey, string, string][]
                ).map(([key, label, align]) => (
                  <th key={key} scope="col" className={`px-3 py-2 ${align}`} aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" className="uppercase hover:text-gray-300" onClick={() => setSort(nextSort(sort, key))} aria-label={`Sort by ${label}`}>
                      {label}
                      {sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  </th>
                ))}
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
                  <td className="px-3 py-1.5 text-xs text-gray-400">
                    {!r.can_push ? 'Not mapped to HaloPSA' : pushText(r.push)}
                    {r.hidden ? ' (hidden)' : ''}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <button type="button" className={ghost} disabled={busy || !canApprove(r)} onClick={() => void approve([r])}>
                      Approve
                    </button>
                  </td>
                </tr>
                {open === rowKey(r) && (
                  <tr data-testid="sync-detail" className="bg-gray-900/50">
                    <td />
                    <td colSpan={7} className="px-3 py-2 text-xs text-gray-300">
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
