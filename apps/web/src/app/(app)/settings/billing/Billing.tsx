"use client";

/**
 * The numbers a bill is made from: what each tool counts for each client (licences bought, machines managed, people covered), the total across clients, how every count moved, and a log of each change.
 * CORE reads the counts from the tools once a day. Backed by GET /api/v1/billing/clients/{id}, /billing/summary and /billing/changes.
 */
import { Fragment, useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

export interface CountRow {
  source: string;
  item: string;
  unit: string;
  count: number;
  available?: number | null;
  change?: number | null;
  first_seen_at: string;
  updated_at: string;
}

export interface TotalRow {
  source: string;
  item: string;
  unit: string;
  clients: number;
  total: number;
  available?: number | null;
  change?: number | null;
}

export interface ChangeRow {
  client_id: string;
  client_name: string;
  source: string;
  item: string;
  unit: string;
  count: number;
  previous_count: number | null;
  observed_at: string;
  unusual?: boolean;
}

export interface ReconcileRow {
  client_id: string;
  client_name: string;
  invoice_item: string;
  billed: number;
  counted: number;
  difference: number;
  parts: { source: string; item: string; count: number }[];
}

export interface MapView {
  mapped: { invoice_item: string; counted: { source: string; item: string }[] }[];
  unmapped: { invoice_item: string; clients: number; suggestion: { source: string; item: string }[] }[];
  counted_items: { source: string; item: string }[];
}

interface Client {
  id: string;
  name: string;
}

/** The tools that send counts, named as people know them (the key is the tool's own name in A.C.O.R.N). */
const TOOL_NAMES: Record<string, string> = {
  cipp: "Microsoft 365 (CIPP)",
  ninjaone: "NinjaOne",
  huntress: "Huntress",
  meraki: "Meraki",
  slide: "Slide",
  autoelevate: "AutoElevate",
  dnsfilter: "DNSFilter",
  fieldeffect: "Field Effect",
  threatmate: "ThreatMate",
  "datto-saas": "Datto SaaS Protection",
};

const toolName = (source: string): string => TOOL_NAMES[source] ?? source.replace(/[-_]/g, " ").replace(/^./, (c) => c.toUpperCase());

/** "+3", "-2", "no change", or a dash when it is not known what the count was. */
export function changeText(change: number | null | undefined): string {
  if (change === null || change === undefined) return "—";
  if (change === 0) return "no change";
  return change > 0 ? `+${change}` : `${change}`;
}

const csvCell = (v: string | number | null | undefined): string => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** The totals as a CSV a person can open in a spreadsheet and set beside an invoice. */
export function totalsCsv(rows: TotalRow[], days: number): string {
  const head = ["Tool", "Item", "Unit", "Clients", "Total", "Not assigned", `Change over ${days} days`];
  const lines = rows.map((r) => [toolName(r.source), r.item, r.unit, r.clients, r.total, r.available ?? "", r.change ?? ""].map(csvCell).join(","));
  return [head.map(csvCell).join(","), ...lines].join("\n") + "\n";
}

/** One client's counts as a CSV. */
export function clientCsv(rows: CountRow[], clientName: string, days: number): string {
  const head = ["Client", "Tool", "Item", "Unit", "Count", "Not assigned", `Change over ${days} days`];
  const lines = rows.map((r) => [clientName, toolName(r.source), r.item, r.unit, r.count, r.available ?? "", r.change ?? ""].map(csvCell).join(","));
  return [head.map(csvCell).join(","), ...lines].join("\n") + "\n";
}

function download(name: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function useJson<T>(url: string | null): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    setData(null);
    authFetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as T;
        if (live) {
          setData(body);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Could not load");
      });
    return () => {
      live = false;
    };
  }, [url]);
  return { data, error };
}

const changeClass = (c: number | null | undefined): string => (c === null || c === undefined || c === 0 ? "text-slate-500" : c > 0 ? "text-emerald-300" : "text-amber-300");

function DaysSelect({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm text-slate-300">
      Compare with
      <select value={days} onChange={(e) => onChange(Number(e.target.value))} className="rounded border border-slate-700 bg-slate-900 px-2 py-1" aria-label="Days">
        <option value={7}>7 days ago</option>
        <option value={30}>30 days ago</option>
        <option value={90}>90 days ago</option>
      </select>
    </label>
  );
}

function Totals() {
  const [days, setDays] = useState(30);
  const { data, error } = useJson<{ rows: TotalRow[] }>(`/api/v1/billing/summary?days=${days}`);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 print:hidden">
        <DaysSelect days={days} onChange={setDays} />
        {data && data.rows.length > 0 ? (
          <button type="button" className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200" onClick={() => download(`license-totals-${days}d.csv`, totalsCsv(data.rows, days))}>
            Download CSV
          </button>
        ) : null}
      </div>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.rows.length === 0 && <p className="text-sm text-slate-400">No counts yet. CORE sends them once a day for each client that is mapped to a tool.</p>}
      {data && data.rows.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="billing-totals">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">Tool</th>
              <th className="pr-3">Item</th>
              <th className="pr-3">Clients</th>
              <th className="pr-3">Total</th>
              <th className="pr-3">Not assigned</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={`${r.source}:${r.item}`} className="border-t border-slate-800 text-slate-300">
                <td className="py-1 pr-3">{toolName(r.source)}</td>
                <td className="pr-3">{r.item}</td>
                <td className="pr-3">{r.clients}</td>
                <td className="pr-3 font-medium">{r.total}</td>
                <td className="pr-3">{r.available ?? "—"}</td>
                <td className={changeClass(r.change)}>{changeText(r.change)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export interface SeriesPoint {
  at: string;
  count: number;
}

/** The points of a series as the "points" attribute of an SVG polyline, scaled into a box (time across, count up; a flat series sits in the middle). */
export function sparkPoints(points: SeriesPoint[], width: number, height: number): string {
  if (points.length === 0) return "";
  const times = points.map((p) => Date.parse(p.at));
  const counts = points.map((p) => p.count);
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const lo = Math.min(...counts);
  const hi = Math.max(...counts);
  const x = (t: number) => (t1 === t0 ? width / 2 : ((t - t0) / (t1 - t0)) * width);
  const y = (c: number) => (hi === lo ? height / 2 : height - ((c - lo) / (hi - lo)) * height);
  return points.map((p, i) => `${x(times[i]).toFixed(1)},${y(p.count).toFixed(1)}`).join(" ");
}

function Trend({ clientId, source, item, days }: { clientId: string; source: string; item: string; days: number }) {
  const { data, error } = useJson<{ points: SeriesPoint[] }>(`/api/v1/billing/clients/${encodeURIComponent(clientId)}/history?source=${encodeURIComponent(source)}&item=${encodeURIComponent(item)}&days=${Math.max(days, 90)}`);
  if (error) return <span role="alert" className="text-xs text-red-300">{error}</span>;
  if (!data) return <span className="text-xs text-slate-500">Loading…</span>;
  const counts = data.points.map((p) => p.count);
  return (
    <div className="flex items-center gap-3" data-testid="billing-trend">
      <svg width={240} height={48} viewBox="0 0 240 48" role="img" aria-label={`${item} over time`}>
        <polyline fill="none" stroke="currentColor" strokeWidth={2} className="text-sky-400" points={sparkPoints(data.points, 236, 44)} transform="translate(2 2)" />
      </svg>
      <span className="text-xs text-slate-400">
        {Math.min(...counts)} to {Math.max(...counts)} over {Math.max(days, 90)} days
      </span>
    </div>
  );
}

function ByClient() {
  const [clients, setClients] = useState<Client[] | null>(null);
  const [clientId, setClientId] = useState("");
  const [days, setDays] = useState(30);
  const [error, setError] = useState<string | null>(null);
  const [trendOf, setTrendOf] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    authFetch("/api/v1/mssp/children")
      .then(async (res) => {
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as Client[];
        if (live) setClients([...body].sort((a, b) => a.name.localeCompare(b.name)));
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : "Could not load the clients");
      });
    return () => {
      live = false;
    };
  }, []);
  const { data, error: loadError } = useJson<{ rows: CountRow[] }>(clientId ? `/api/v1/billing/clients/${encodeURIComponent(clientId)}?days=${days}` : null);
  const name = clients?.find((c) => c.id === clientId)?.name ?? "";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 print:hidden">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          Client
          <select value={clientId} onChange={(e) => setClientId(e.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1" aria-label="Client">
            <option value="">Pick a client</option>
            {(clients ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <DaysSelect days={days} onChange={setDays} />
        {data && data.rows.length > 0 ? (
          <button type="button" className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200" onClick={() => download(`${name || "client"}-licenses.csv`, clientCsv(data.rows, name, days))}>
            Download CSV
          </button>
        ) : null}
      </div>
      {(error || loadError) && <p role="alert" className="text-sm text-red-300">{error ?? loadError}</p>}
      {clientId && data && data.rows.length === 0 && <p className="text-sm text-slate-400">No counts for this client yet. It needs to be mapped to a tool CORE reads.</p>}
      {data && data.rows.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="billing-client">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">Tool</th>
              <th className="pr-3">Item</th>
              <th className="pr-3">Count</th>
              <th className="pr-3">Not assigned</th>
              <th className="pr-3">Change</th>
              <th className="pr-3">First seen</th>
              <th className="print:hidden" />
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const key = `${r.source}:${r.item}`;
              return (
                <Fragment key={key}>
                  <tr className="border-t border-slate-800 text-slate-300">
                    <td className="py-1 pr-3">{toolName(r.source)}</td>
                    <td className="pr-3">{r.item}</td>
                    <td className="pr-3 font-medium">{r.count}</td>
                    <td className="pr-3">{r.available ?? "—"}</td>
                    <td className={`pr-3 ${changeClass(r.change)}`}>{changeText(r.change)}</td>
                    <td className="pr-3 text-xs text-slate-500">{new Date(r.first_seen_at).toLocaleDateString()}</td>
                    <td className="print:hidden">
                      <button type="button" className="text-xs text-slate-500 underline hover:text-slate-300" onClick={() => setTrendOf(trendOf === key ? null : key)}>
                        {trendOf === key ? "Hide trend" : "Trend"}
                      </button>
                    </td>
                  </tr>
                  {trendOf === key ? (
                    <tr className="text-slate-300">
                      <td colSpan={7} className="pb-2">
                        <Trend clientId={clientId} source={r.source} item={r.item} days={days} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** "uses 2 more than billed", "billed for 3 more than used", or "matches". */
export function differenceText(d: number): string {
  if (d === 0) return "matches";
  return d > 0 ? `uses ${d} more than billed` : `billed for ${-d} more than used`;
}

/** What to do to the invoice line to make it match what the tools count: "raise by 2", "lower by 3" or "no change". */
export function trueUpAction(difference: number): string {
  if (difference === 0) return "no change";
  return difference > 0 ? `raise by ${difference}` : `lower by ${-difference}`;
}

/** A print-ready true-up list: one row per invoice line that disagrees, grouped by client name, with the quantity to change it to. Quantities only. */
export function trueUpCsv(rows: ReconcileRow[]): string {
  const cell = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [["Client", "Invoice line", "Billed now", "Change to", "Action", "Counted from"].map(cell).join(",")];
  const sorted = [...rows].filter((r) => r.difference !== 0).sort((a, b) => a.client_name.localeCompare(b.client_name) || a.invoice_item.localeCompare(b.invoice_item));
  for (const r of sorted) {
    lines.push([r.client_name, r.invoice_item, r.billed, r.counted, trueUpAction(r.difference), r.parts.map((p) => `${toolName(p.source)} ${p.item}: ${p.count}`).join("; ")].map(cell).join(","));
  }
  return lines.join("\n");
}

function Reconcile() {
  const { data, error } = useJson<{ rows: ReconcileRow[]; unmapped_lines: number }>("/api/v1/billing/reconcile");
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Each invoice line HaloPSA bills, against the tool counts it is mapped to. Only mapped lines are compared; map more under Invoice mapping.</p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.unmapped_lines > 0 && <p className="text-xs text-amber-300">{data.unmapped_lines} billed line{data.unmapped_lines === 1 ? "" : "s"} left out because nobody has mapped {data.unmapped_lines === 1 ? "it" : "them"} yet.</p>}
      {data && data.rows.length === 0 && <p className="text-sm text-slate-400">Nothing disagrees.</p>}
      {data && data.rows.length > 0 && (
        <button type="button" className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 print:hidden" onClick={() => download("true-up.csv", trueUpCsv(data.rows))}>
          Download true-up list (CSV)
        </button>
      )}
      {data && data.rows.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="billing-reconcile">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">Client</th>
              <th className="pr-3">Invoice line</th>
              <th className="pr-3">Billed</th>
              <th className="pr-3">Counted</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={`${r.client_id}:${r.invoice_item}`} className="border-t border-slate-800 text-slate-300">
                <td className="py-1 pr-3">{r.client_name}</td>
                <td className="pr-3">
                  {r.invoice_item}
                  <div className="text-xs text-slate-500">{r.parts.map((p) => `${toolName(p.source)} ${p.item}: ${p.count}`).join("; ")}</div>
                </td>
                <td className="pr-3">{r.billed}</td>
                <td className="pr-3">{r.counted}</td>
                <td className={r.difference > 0 ? "text-amber-300" : "text-sky-300"}>{differenceText(r.difference)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Mapping() {
  const [reload, setReload] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const { data, error } = useJson<MapView>(`/api/v1/billing/map?r=${reload}`);
  const save = async (invoice_item: string, counted: { source: string; item: string }[]) => {
    try {
      const res = await authFetch("/api/v1/billing/map", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ invoice_item, counted }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      setReload((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
    }
  };
  const saveQuiet = async (invoice_item: string, counted: { source: string; item: string }[]): Promise<boolean> => {
    try {
      const res = await authFetch("/api/v1/billing/map", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ invoice_item, counted }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      return true;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
      setReload((n) => n + 1);
      return false;
    }
  };
  const remove = async (invoice_item: string) => {
    try {
      const res = await authFetch(`/api/v1/billing/map?invoice_item=${encodeURIComponent(invoice_item)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      setReload((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not remove");
    }
  };
  const withSuggestion = (data?.unmapped ?? []).filter((u) => u.suggestion.length > 0);
  const useAll = async () => {
    for (const u of withSuggestion) {
      const ok = await saveQuiet(u.invoice_item, u.suggestion);
      if (!ok) return;
    }
    setProblem(null);
    setReload((n) => n + 1);
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">Say which tool counts each invoice line should equal. A suggestion is a guess from the line&apos;s name: use it only if it is right. For a line with no suggestion, pick the tool count yourself.</p>
      {(error || problem) && <p role="alert" className="text-sm text-red-300">{error ?? problem}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && (
        <>
          <section>
            <h3 className="mb-1 text-sm uppercase text-slate-500">Mapped</h3>
            {(data.mapped ?? []).length === 0 ? (
              <p className="text-sm text-slate-400">Nothing is mapped yet.</p>
            ) : (
              <table className="w-full text-left text-sm" data-testid="mapped-lines">
                <tbody>
                  {(data.mapped ?? []).map((m) => (
                    <tr key={m.invoice_item} className="border-t border-slate-800 text-slate-300">
                      <td className="py-1 pr-3">{m.invoice_item}</td>
                      <td className="pr-3 text-xs text-slate-400">{m.counted.map((c) => `${toolName(c.source)} ${c.item}`).join(" + ")}</td>
                      <td>
                        <button type="button" className="text-xs text-slate-500 underline hover:text-slate-300" onClick={() => void remove(m.invoice_item)}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section>
            <div className="mb-1 flex items-center justify-between gap-3">
              <h3 className="text-sm uppercase text-slate-500">Billed lines still to map</h3>
              {withSuggestion.length > 0 ? (
                <button type="button" className="rounded border border-sky-500/50 px-2 py-0.5 text-xs text-sky-200 print:hidden" onClick={() => void useAll()}>
                  Use all {withSuggestion.length} suggestions
                </button>
              ) : null}
            </div>
            {(data.unmapped ?? []).length === 0 ? (
              <p className="text-sm text-slate-400">Every billed line is mapped.</p>
            ) : (
              <table className="w-full text-left text-sm" data-testid="unmapped-lines">
                <tbody>
                  {(data.unmapped ?? []).map((u) => (
                    <tr key={u.invoice_item} className="border-t border-slate-800 text-slate-300">
                      <td className="py-1 pr-3">{u.invoice_item}</td>
                      <td className="pr-3 text-xs text-slate-500">{u.clients} clients</td>
                      <td className="pr-3 text-xs text-slate-400">{u.suggestion.length > 0 ? u.suggestion.map((c) => `${toolName(c.source)} ${c.item}`).join(" + ") : "no suggestion"}</td>
                      <td>
                        {u.suggestion.length > 0 ? (
                          <button type="button" className="text-xs text-sky-300 underline hover:text-sky-200" onClick={() => void save(u.invoice_item, u.suggestion)}>
                            Use suggestion
                          </button>
                        ) : (
                          <select
                            aria-label={`Map ${u.invoice_item} to`}
                            className="max-w-[16rem] rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-xs text-slate-300"
                            value=""
                            onChange={(e) => {
                              const [source, ...rest] = e.target.value.split("|");
                              if (source) void save(u.invoice_item, [{ source, item: rest.join("|") }]);
                            }}
                          >
                            <option value="">Map to…</option>
                            {(data.counted_items ?? []).map((c) => (
                              <option key={`${c.source}|${c.item}`} value={`${c.source}|${c.item}`}>
                                {toolName(c.source)}: {c.item}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Changes() {
  const [days, setDays] = useState(30);
  const { data, error } = useJson<ChangeRow[]>(`/api/v1/billing/changes?days=${days}`);
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-slate-300 print:hidden">
        Last
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-slate-700 bg-slate-900 px-2 py-1" aria-label="Days">
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
        </select>
      </label>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.length === 0 && <p className="text-sm text-slate-400">No count changed in that time.</p>}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="billing-changes">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">When</th>
              <th className="pr-3">Client</th>
              <th className="pr-3">Tool</th>
              <th className="pr-3">Item</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {data.map((c, i) => (
              <tr key={`${c.client_id}:${c.source}:${c.item}:${i}`} className="border-t border-slate-800 text-slate-300">
                <td className="py-1 pr-3 text-xs text-slate-500">{new Date(c.observed_at).toLocaleString()}</td>
                <td className="pr-3">{c.client_name}</td>
                <td className="pr-3">{toolName(c.source)}</td>
                <td className="pr-3">{c.item}</td>
                <td className={changeClass(c.previous_count === null ? c.count : c.count - c.previous_count)}>
                  {c.previous_count === null ? `new: ${c.count}` : `${c.previous_count} → ${c.count}`}
                  {c.unusual ? <span className="ml-2 rounded bg-amber-900/50 px-1 text-xs text-amber-300" title="Moved by more than a fifth">unusual</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function gapText(gap: number): string {
  return gap < 0 ? `counts ${-gap} fewer` : `counts ${gap} more`;
}

function DataQuality() {
  const quality = useJson<{ no_counts?: string[]; rows: { client_id: string; client_name: string; tool: string; tool_count: number; baseline_count: number; gap: number }[] }>("/api/v1/billing/data-quality");
  const silent = useJson<{ client_id: string; client_name: string; source: string; last_reported_at: string; days_ago: number; silent: boolean }[]>("/api/v1/billing/last-reported?only_silent=true");
  const error = quality.error ?? silent.error;
  return (
    <div className="space-y-6">
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Tools that count different machines than NinjaOne</h2>
        <p className="text-sm text-slate-400">A security tool whose count for a client is at least three machines and a fifth away from what NinjaOne manages. A tool with no count for the client is not listed here.</p>
        {!quality.data && !quality.error && <p className="text-sm text-slate-500">Loading…</p>}
        {quality.data && quality.data.rows.length === 0 && <p className="text-sm text-slate-400">No tool disagrees with NinjaOne.</p>}
        {quality.data && quality.data.rows.length > 0 && (
          <table className="w-full text-left text-sm" data-testid="billing-disagree">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-3">Client</th>
                <th className="pr-3">Tool</th>
                <th className="pr-3">Tool counts</th>
                <th className="pr-3">NinjaOne manages</th>
                <th>Gap</th>
              </tr>
            </thead>
            <tbody>
              {quality.data.rows.map((r) => (
                <tr key={`${r.client_id}:${r.tool}`} className="border-t border-slate-800 text-slate-300">
                  <td className="py-1 pr-3">{r.client_name}</td>
                  <td className="pr-3">{toolName(r.tool)}</td>
                  <td className="pr-3">{r.tool_count}</td>
                  <td className="pr-3">{r.baseline_count}</td>
                  <td className={r.gap < 0 ? "text-amber-300" : "text-sky-300"}>{gapText(r.gap)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Tools with clients but no counts</h2>
        <p className="text-sm text-slate-400">These tools have clients mapped to them but have never stored a count. Some count nothing by design (a detection feed); a tool that should count and is listed here needs a look.</p>
        {quality.data && (quality.data.no_counts ?? []).length === 0 && <p className="text-sm text-slate-400">Every mapped tool has stored counts.</p>}
        {quality.data && (quality.data.no_counts ?? []).length > 0 && <p className="text-sm text-slate-300" data-testid="billing-no-counts">{(quality.data.no_counts ?? []).map(toolName).join(', ')}</p>}
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Tools that stopped reporting</h2>
        <p className="text-sm text-slate-400">No count from the tool for the client in more than two days: a stopped feed, a removed mapping or lost access.</p>
        {!silent.data && !silent.error && <p className="text-sm text-slate-500">Loading…</p>}
        {silent.data && silent.data.length === 0 && <p className="text-sm text-slate-400">Every tool reported in the last two days.</p>}
        {silent.data && silent.data.length > 0 && (
          <table className="w-full text-left text-sm" data-testid="billing-silent">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-3">Client</th>
                <th className="pr-3">Tool</th>
                <th>Last reported</th>
              </tr>
            </thead>
            <tbody>
              {silent.data.map((r) => (
                <tr key={`${r.client_id}:${r.source}`} className="border-t border-slate-800 text-slate-300">
                  <td className="py-1 pr-3">{r.client_name}</td>
                  <td className="pr-3">{toolName(r.source)}</td>
                  <td className="text-amber-300">{r.days_ago} days ago</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export function Billing() {
  const [tab, setTab] = useState<"totals" | "client" | "changes" | "reconcile" | "mapping" | "quality">("totals");
  const tabs: [typeof tab, string][] = [["totals", "Totals by tool"], ["client", "By client"], ["changes", "Changes"], ["reconcile", "Billed vs counted"], ["mapping", "Invoice mapping"], ["quality", "Data quality"]];
  return (
    <div className="space-y-4 p-6">
      <div>
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-xl font-semibold text-slate-100">Licences and counts</h1>
          <button type="button" onClick={() => window.print()} className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 print:hidden">
            Print
          </button>
        </div>
        <p className="mt-1 text-sm text-slate-400">What each tool counts for each client, read once a day, and every change, to check an invoice against.</p>
      </div>
      <div role="tablist" className="flex flex-wrap gap-2 print:hidden">
        {tabs.map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)} className={`rounded border px-3 py-1 text-sm ${tab === id ? "border-sky-500/60 text-sky-200" : "border-slate-700 text-slate-300"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "totals" ? <Totals /> : tab === "client" ? <ByClient /> : tab === "reconcile" ? <Reconcile /> : tab === "mapping" ? <Mapping /> : tab === "quality" ? <DataQuality /> : <Changes />}
    </div>
  );
}
