'use client';

/**
 * Settings > Finance > Software costs: the software vendors QuickBooks booked costs to, what each billed in the latest month, and which counts stand behind each (a tool and an item, such as HaloPSA's "Huntress EDR").
 * Net income carries a vendor's bill to the clients that use it in proportion to those counts, as the License Database does; a vendor with no count is spread by revenue like any company-wide cost.
 * Backed by /api/v1/finance/software.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { sortedBy, type SortState, type SortValue } from '@/lib/tableSort';
import { SortHeader } from './SortHeader';

export interface Counted {
  source: string;
  item: string;
}
export interface VendorRow {
  vendor: string;
  account: '5100' | '5500';
  latest_month: string;
  latest_amount: string | number;
  mapped: Counted[];
  licenses: number | null;
  per_license: string | number | null;
}
export interface Software {
  have_costs: boolean;
  latest_month: string | null;
  vendors: VendorRow[];
  counted_items: Counted[];
}

export const ACCOUNT_LABEL = { '5500': 'Add-on', '5100': 'Support and maintenance' } as const;

/** How a vendor stands, in words (pure): what it billed, how many licenses are counted behind it and what one costs, or that nothing is counted. */
export function vendorSummary(v: VendorRow): string {
  if (v.mapped.length === 0) return 'No count chosen: spread by revenue';
  if (!v.licenses) return 'Counts chosen but none are held: spread by revenue';
  return `${v.licenses} licenses, about $${Number(v.per_license ?? 0).toFixed(2)} each`;
}

/** The counts that match what is typed (pure): every word must appear in the tool or the item, whatever the case. */
export function filterCounted(items: Counted[], text: string): Counted[] {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  return items.filter((c) => words.every((w) => `${c.source} ${c.item}`.toLowerCase().includes(w)));
}

const key = (c: Counted) => `${c.source}\u0000${c.item}`;
const ghost = 'rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50';
const input = 'rounded-md border border-gray-700 bg-gray-950/60 px-2 py-1 text-sm text-gray-100';
const th = 'px-3 py-2 text-left';
const money = (v: string | number) => `$${Number(v).toFixed(2)}`;

export function SoftwareCostsPanel() {
  const [data, setData] = useState<Software | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sort, setSort] = useState<SortState | null>({ key: 'latest_amount', desc: true });
  const [editing, setEditing] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/finance/software');
      if (res.ok) {
        const body = (await res.json()) as Partial<Software>;
        if (Array.isArray(body.vendors) && Array.isArray(body.counted_items)) setData(body as Software);
      }
    } catch {
      /* shows nothing */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => (data ? sortedBy(data.vendors, (v) => (sort ? ((v as unknown as Record<string, unknown>)[sort.key] as SortValue) : v.vendor), sort?.desc ?? true) : []), [data, sort]);
  const shown = useMemo(() => filterCounted(data?.counted_items ?? [], filter), [data, filter]);

  const open = (v: VendorRow) => {
    setEditing(v.vendor);
    setPicked(new Set(v.mapped.map(key)));
    setFilter('');
    setProblem(null);
  };
  const save = async (vendor: string) => {
    setBusy(true);
    setProblem(null);
    try {
      const counted = (data?.counted_items ?? []).filter((c) => picked.has(key(c)));
      const res = await authFetch('/api/v1/finance/software/map', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vendor, counted }) });
      if (!res.ok) return setProblem(res.status === 403 ? 'You can read this but not change it.' : `That was not saved (${res.status}).`);
      setEditing(null);
      await load();
    } catch {
      setProblem('That could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  if (data === null) return null;
  return (
    <section className="space-y-2" data-testid="software-costs">
      <h2 className="text-sm font-semibold text-gray-200">Software costs</h2>
      <p className="text-xs text-gray-500">
        What each software vendor billed in {data.latest_month ?? 'the latest month'} (from QuickBooks, read only). Choose the counts that say how many licenses of a vendor each client has (the count the vendor charges us on, including licenses we do not bill the client for: prefer the tool's own count to the quantity on the invoice, which leaves those out), and Net income carries the bill to those clients in proportion, for add-on and for support and maintenance software; a vendor with no count is spread by revenue.
      </p>
      {!data.have_costs ? <p className="text-xs text-amber-300">QuickBooks has not sent the vendor bills yet (CORE reads them once a day).</p> : null}
      {problem ? <p className="text-sm text-red-300" role="alert">{problem}</p> : null}
      {data.have_costs ? (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <SortHeader label="Vendor" field="vendor" sort={sort} onSort={setSort} text className={th} />
                <SortHeader label="Account" field="account" sort={sort} onSort={setSort} text className={th} />
                <SortHeader label="Billed" field="latest_amount" sort={sort} onSort={setSort} className={th} />
                <th className={th}>Counts behind it</th>
                <th className={th}>Result</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800 text-gray-200">
              {rows.map((v) => (
                <tr key={`${v.account}|${v.vendor}`} className="align-top">
                  <td className="px-3 py-1.5">{v.vendor}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-400">{ACCOUNT_LABEL[v.account]}</td>
                  <td className="px-3 py-1.5 tabular-nums">{money(v.latest_amount)}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-300">
                    {v.mapped.length === 0 ? '—' : v.mapped.map((c) => `${c.source}: ${c.item}`).join('; ')}
                    {editing === v.vendor ? (
                      <div className="mt-2 space-y-1 rounded border border-gray-700 bg-gray-950/60 p-2" data-testid="count-picker">
                        <input className={`${input} w-64`} placeholder="Find a count (tool or item)" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find a count" />
                        <ul className="max-h-48 overflow-y-auto">
                          {shown.map((c) => (
                            <li key={key(c)}>
                              <label className="flex items-center gap-2 text-xs text-gray-200">
                                <input
                                  type="checkbox"
                                  checked={picked.has(key(c))}
                                  onChange={(e) => {
                                    const next = new Set(picked);
                                    if (e.target.checked) next.add(key(c));
                                    else next.delete(key(c));
                                    setPicked(next);
                                  }}
                                />
                                {c.source}: {c.item}
                              </label>
                            </li>
                          ))}
                          {shown.length === 0 ? <li className="text-xs text-gray-500">No count matches.</li> : null}
                        </ul>
                        <div className="flex gap-2">
                          <button type="button" className={ghost} disabled={busy} onClick={() => void save(v.vendor)}>Save</button>
                          <button type="button" className={ghost} disabled={busy} onClick={() => setEditing(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-gray-400">{vendorSummary(v)}</td>
                  <td className="px-3 py-1.5">
                    {editing === v.vendor ? null : (
                      <button type="button" className={ghost} onClick={() => open(v)} aria-label={`Choose the counts behind ${v.vendor}`}>
                        Choose counts
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
