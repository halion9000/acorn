"use client";

/**
 * Every client's tool checks side by side: who is worst, what is about to expire or lapse, who still runs Windows 10, which backups are failing, who has administrators without two-step sign-in, and what
 * changed lately. Read only. Backed by GET /api/v1/client-posture/fleet/summary, /fleet/boards/{board} and /fleet/changes.
 */
import { useEffect, useState } from "react";
import { boardCsv, downloadCsv, worstCsv } from "./exportCsv";
import { addView, loadViews, removeView, storeViews, type SavedView } from "./savedViews";
import Link from "next/link";

import { authFetch } from "@/lib/auth-session";
import { TOOL_CHECK_LABELS } from "../client-posture/ClientPosture";

export interface FleetClient {
  client_id: string;
  client_name: string | null;
  score: number | null;
  met: number;
  partly: number;
  not_met: number;
  accepted: number;
  stale_tools: string[];
  target?: number | null;
  below_target?: boolean;
}

export interface BoardRow {
  client_id: string;
  client_name: string;
  source: string;
  key: string;
  status: string;
  evidence: string;
  since?: string | null;
  accepted: boolean;
  items?: string[];
  owner?: string | null;
  due_date?: string | null;
  overdue?: boolean;
}

export interface FleetChange {
  client_id: string;
  client_name: string;
  key: string;
  source: string;
  status: string;
  previous_status: string | null;
  observed_at: string;
}

export interface Coverage {
  tools: { vendor: string; clients: number }[];
  clients: { client_id: string; client_name: string; tools: string[]; missing: string[] }[];
}

export type BoardMeta = Record<string, { title: string; keys: string[] }>;

const STATUS_TEXT: Record<string, { text: string; className: string }> = {
  met: { text: "Good", className: "text-emerald-300" },
  partly: { text: "Needs attention", className: "text-amber-300" },
  not_met: { text: "Problem", className: "text-red-300" },
};

/** The page a client's own posture is on, opened on that client. */
export function clientHref(clientId: string): string {
  return `/settings/client-posture?client=${encodeURIComponent(clientId)}`;
}

/** "Worse", "better" or "new" for a change, from what the check was before. */
export function changeWord(c: Pick<FleetChange, "status" | "previous_status">): "new" | "worse" | "better" | "same" {
  if (!c.previous_status) return "new";
  const rank: Record<string, number> = { met: 0, partly: 1, not_met: 2 };
  const a = rank[c.status] ?? 0;
  const b = rank[c.previous_status] ?? 0;
  return a > b ? "worse" : a < b ? "better" : "same";
}

function useJson<T>(url: string | null, reload = 0): { data: T | null; error: string | null } {
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
  }, [url, reload]);
  return { data, error };
}

export interface Compare {
  score: number | null;
  fleet_average: number | null;
  size: number;
  similar_average: number | null;
  similar_clients: number;
}

/** "Fleet average 72%; 14 clients of a similar size average 65%." */
export function compareText(c: Compare): string {
  const fleet = c.fleet_average === null ? "" : `Fleet average ${c.fleet_average}%`;
  const similar = c.similar_average === null ? (c.size > 0 ? "no clients of a similar size to compare with" : "") : `${c.similar_clients} client${c.similar_clients === 1 ? "" : "s"} of a similar size average ${c.similar_average}%`;
  return [fleet, similar].filter(Boolean).join("; ") + (fleet || similar ? "." : "");
}

function WhyRow({ clientId }: { clientId: string }) {
  const { data, error } = useJson<Breakdown>(`/api/v1/client-posture/${encodeURIComponent(clientId)}/score-breakdown`);
  const compare = useJson<Compare>(`/api/v1/client-posture/${encodeURIComponent(clientId)}/compare`);
  if (error) return <span className="text-xs text-red-300">{error}</span>;
  if (!data) return <span className="text-xs text-slate-500">Loading…</span>;
  if (data.rows.length === 0) return <span className="text-xs text-slate-400">Nothing is costing this client points.</span>;
  return (
    <div>
    {compare.data ? <p className="text-xs text-slate-500" data-testid={`compare-${clientId}`}>{compareText(compare.data)}</p> : null}
    <ul className="text-xs text-slate-400" data-testid={`why-${clientId}`}>
      {data.rows.map((r) => (
        <li key={r.key}>
          {r.key.replace(/_/g, " ")} ({TOOL_CHECK_LABELS[r.source] ?? r.source}, {STATUS_TEXT[r.status]?.text.toLowerCase() ?? r.status}
          {r.weight > 1 ? `, counts ${r.weight} times` : ""}): {pointsText(r.points_lost)}
        </li>
      ))}
    </ul>
    </div>
  );
}

function Worst() {
  const [why, setWhy] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const { data, error } = useJson<{ clients: FleetClient[]; average_score?: number | null }>("/api/v1/client-posture/fleet/summary", reload);
  const setTarget = async (c: FleetClient) => {
    const answer = window.prompt(`Target score for ${c.client_name ?? "this client"} (1 to 100). Leave empty to remove it.`, c.target ? String(c.target) : "");
    if (answer === null) return;
    const value = answer.trim() === "" ? null : Number(answer);
    if (value !== null && (!Number.isInteger(value) || value < 1 || value > 100)) {
      setProblem("A target is a whole number from 1 to 100.");
      return;
    }
    try {
      const res = await authFetch(`/api/v1/client-posture/${encodeURIComponent(c.client_id)}/target`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target: value }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      setReload((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
    }
  };
  if (error) return <p role="alert" className="text-sm text-red-300">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (data.clients.length === 0) return <p className="text-sm text-slate-400">No client has sent checks yet.</p>;
  return (
    <>
    {problem && <p role="alert" className="mb-2 text-sm text-red-300">{problem}</p>}
    <button type="button" className="mb-2 rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 print:hidden" onClick={() => downloadCsv("fleet-posture.csv", worstCsv(data.clients))}>
      Download CSV
    </button>
    {data.average_score != null && <p className="mb-2 text-sm text-slate-400" data-testid="fleet-average">Fleet average: {data.average_score}% across {data.clients.filter((c) => c.score !== null).length} clients with a score.</p>}
    <table className="w-full text-left text-sm" data-testid="fleet-worst">
      <thead className="text-xs uppercase text-slate-500">
        <tr>
          <th className="py-1 pr-3">Client</th>
          <th className="pr-3">Score</th>
          <th className="pr-3">Target</th>
          <th className="pr-3">Problems</th>
          <th className="pr-3">Need attention</th>
          <th className="pr-3">Accepted</th>
          <th>Not updating</th>
        </tr>
      </thead>
      <tbody>
        {data.clients.map((c) => (
          <tr key={c.client_id} className="border-t border-slate-800 text-slate-300" data-testid={`fleet-client-${c.client_id}`}>
            <td className="py-1 pr-3">
              <Link href={clientHref(c.client_id)} className="text-sky-300 hover:underline">
                {c.client_name ?? c.client_id}
              </Link>
            </td>
            <td className="pr-3">
              {c.score === null ? "—" : `${c.score}%`}{" "}
              {c.score !== null && c.score < 100 ? (
                <button type="button" className="text-xs text-slate-500 underline hover:text-slate-300 print:hidden" onClick={() => setWhy(why === c.client_id ? null : c.client_id)}>
                  {why === c.client_id ? "Hide" : "Why"}
                </button>
              ) : null}
              {why === c.client_id ? <WhyRow clientId={c.client_id} /> : null}
            </td>
            <td className="pr-3">
              {c.target ? <span className={c.below_target ? "text-red-300" : "text-slate-300"}>{c.target}%{c.below_target ? " (below)" : ""}</span> : <span className="text-slate-600">none</span>}{" "}
              <button type="button" className="text-xs text-slate-500 underline hover:text-slate-300 print:hidden" onClick={() => void setTarget(c)}>
                {c.target ? "Change" : "Set"}
              </button>
            </td>
            <td className={`pr-3 ${c.not_met > 0 ? "text-red-300" : ""}`}>{c.not_met}</td>
            <td className={`pr-3 ${c.partly > 0 ? "text-amber-300" : ""}`}>{c.partly}</td>
            <td className="pr-3">{c.accepted}</td>
            <td className="text-xs text-amber-300">{c.stale_tools.map((t) => TOOL_CHECK_LABELS[t] ?? t).join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  );
}

/** The rows picked on a board, grouped by check: each check is accepted for its clients in one request. Keys are "client_id|check_key". */
export function groupSelection(selected: Iterable<string>): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const k of selected) {
    const at = k.indexOf("|");
    const clientId = k.slice(0, at);
    const key = k.slice(at + 1);
    out.set(key, [...(out.get(key) ?? []), clientId]);
  }
  return out;
}

/** A board of related checks, or (with `source`) every check one tool reported, worst first, with the same accept and CSV tools. */
function Board({ board, title, source }: { board: string; title: string; source?: string }) {
  const [reload, setReload] = useState(0);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [problem, setProblem] = useState<string | null>(null);
  const { data, error } = useJson<{ rows: BoardRow[] }>(source ? `/api/v1/client-posture/fleet/tools/${encodeURIComponent(source)}/checks` : `/api/v1/client-posture/fleet/boards/${encodeURIComponent(board)}`, reload);
  const toggle = (k: string) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    return next;
  });
  const acceptPicked = async (notApplicable: boolean) => {
    const reason = window.prompt(notApplicable ? "Why do these checks not apply to these clients?" : "Why are these accepted for these clients?");
    if (!reason || reason.trim().length < 3) return;
    let days: number | undefined;
    if (!notApplicable) {
      const answer = window.prompt("For how many days? Leave empty to accept until you remove it.", "90");
      if (answer && answer.trim() !== "") days = Number(answer);
    }
    try {
      for (const [key, clientIds] of groupSelection(picked)) {
        const res = await authFetch("/api/v1/client-posture/fleet/acceptances", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, client_ids: clientIds, reason: reason.trim(), not_applicable: notApplicable, ...(days !== undefined ? { expires_in_days: days } : {}) }),
        });
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as { skipped?: { detail: string }[] };
        if ((body.skipped ?? []).length > 0) throw new Error(`${body.skipped!.length} could not be done: ${body.skipped![0].detail}`);
      }
      setProblem(null);
      setPicked(new Set());
      setReload((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
      setReload((n) => n + 1);
    }
  };
  if (error) return <p role="alert" className="text-sm text-red-300">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (data.rows.length === 0) return <p className="text-sm text-slate-400">Nothing on the {title.toLowerCase()} board needs attention.</p>;
  return (
    <>
    {problem && <p role="alert" className="mb-2 text-sm text-red-300">{problem}</p>}
    <div className="mb-2 flex items-center gap-3 text-xs print:hidden">
      <button type="button" className="rounded border border-slate-600 px-2 py-0.5 text-slate-200" onClick={() => downloadCsv(`fleet-${board}.csv`, boardCsv(data.rows))}>
        Download CSV
      </button>
      <span className="text-slate-500">{picked.size} picked</span>
      <button type="button" disabled={picked.size === 0} className="rounded border border-slate-600 px-2 py-0.5 text-slate-200 disabled:opacity-40" onClick={() => void acceptPicked(false)}>
        Accept picked
      </button>
      <button type="button" disabled={picked.size === 0} className="rounded border border-slate-600 px-2 py-0.5 text-slate-200 disabled:opacity-40" onClick={() => void acceptPicked(true)}>
        Not applicable for picked
      </button>
    </div>
    <table className="w-full text-left text-sm" data-testid={`fleet-board-${board}`}>
      <thead className="text-xs uppercase text-slate-500">
        <tr>
          <th className="w-6 py-1 print:hidden" />
          <th className="py-1 pr-3">Client</th>
          <th className="pr-3">Tool</th>
          <th className="pr-3">Status</th>
          <th>What it saw</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((r) => {
          const st = STATUS_TEXT[r.status] ?? STATUS_TEXT.partly;
          return (
            <tr key={`${r.client_id}:${r.key}`} className={`border-t border-slate-800 text-slate-300 ${r.accepted ? "opacity-60" : ""}`}>
              <td className="py-1 print:hidden">
                <input type="checkbox" aria-label={`Pick ${r.client_name} ${r.key}`} checked={picked.has(`${r.client_id}|${r.key}`)} onChange={() => toggle(`${r.client_id}|${r.key}`)} />
              </td>
              <td className="py-1 pr-3">
                <Link href={clientHref(r.client_id)} className="text-sky-300 hover:underline">
                  {r.client_name}
                </Link>
              </td>
              <td className="pr-3">{TOOL_CHECK_LABELS[r.source] ?? r.source}</td>
              <td className={`pr-3 ${st.className}`}>
                {st.text}
                {r.accepted ? " (accepted)" : ""}
              </td>
              <td className="text-xs text-slate-400">
                {r.evidence}
                {r.owner ? (
                  <div className={r.overdue ? "text-red-300" : "text-slate-500"} data-testid={`board-owner-${r.client_id}-${r.key}`}>
                    Owner: {r.owner}
                    {r.due_date ? `, due ${r.due_date}` : ""}
                    {r.overdue ? " (overdue)" : ""}
                  </div>
                ) : null}
                {r.items && r.items.length > 0 ? (
                  <details className="mt-0.5">
                    <summary className="cursor-pointer text-slate-500">Which ones ({r.items.length})</summary>
                    <ul className="list-disc pl-4">
                      {r.items.map((i) => (
                        <li key={i}>{i}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </>
  );
}

function CoverageTab() {
  const { data, error } = useJson<Coverage>("/api/v1/client-posture/fleet/coverage");
  if (error) return <p role="alert" className="text-sm text-red-300">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (data.tools.length === 0) return <p className="text-sm text-slate-400">No client is mapped to a tool yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="text-left text-xs" data-testid="fleet-coverage">
        <thead className="text-slate-500">
          <tr>
            <th className="py-1 pr-3">Client</th>
            {data.tools.map((t) => (
              <th key={t.vendor} className="px-2 text-center" title={`${t.clients} clients`}>
                {TOOL_CHECK_LABELS[t.vendor] ?? t.vendor}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.clients.map((c) => (
            <tr key={c.client_id} className="border-t border-slate-800 text-slate-300" data-testid={`coverage-${c.client_id}`}>
              <td className="py-1 pr-3">
                <Link href={clientHref(c.client_id)} className="text-sky-300 hover:underline">
                  {c.client_name}
                </Link>
              </td>
              {data.tools.map((t) => (
                <td key={t.vendor} className={`px-2 text-center ${c.tools.includes(t.vendor) ? "text-emerald-300" : "text-slate-600"}`}>
                  {c.tools.includes(t.vendor) ? "✓" : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Changes({ initialDays = 1, onDays }: { initialDays?: number; onDays?: (d: number) => void }) {
  const [days, setDays] = useState(initialDays);
  const { data, error } = useJson<FleetChange[]>(`/api/v1/client-posture/fleet/changes?days=${days}`);
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm text-slate-300">
        Last
        <select value={days} onChange={(e) => {
            setDays(Number(e.target.value));
            onDays?.(Number(e.target.value));
          }} className="rounded border border-slate-700 bg-slate-900 px-2 py-1" aria-label="Days">
          <option value={1}>day</option>
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
        </select>
      </label>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.length === 0 && <p className="text-sm text-slate-400">Nothing changed in that time.</p>}
      {data && data.length > 0 && (
        <ul className="space-y-1 text-sm" data-testid="fleet-changes">
          {data.map((c, i) => (
            <li key={`${c.client_id}:${c.key}:${i}`} className="text-slate-300">
              <span className={changeWord(c) === "worse" ? "text-red-300" : changeWord(c) === "better" ? "text-emerald-300" : "text-slate-400"}>{changeWord(c)}</span>{" "}
              <Link href={clientHref(c.client_id)} className="text-sky-300 hover:underline">
                {c.client_name}
              </Link>
              : {c.key.replace(/_/g, " ")} is now {STATUS_TEXT[c.status]?.text.toLowerCase() ?? c.status}
              <span className="ml-2 text-xs text-slate-500">{new Date(c.observed_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export interface FleetAcceptance {
  client_id: string;
  client_name: string;
  key: string;
  reason: string;
  accepted_at: string;
  expires_at: string | null;
  not_applicable?: boolean;
}

/** "ends in 5 days", "ended" (never shown, the API leaves those out) or "no end date". */
export function endsText(expiresAt: string | null, nowMs: number = Date.now()): string {
  if (!expiresAt) return "no end date";
  const days = Math.ceil((Date.parse(expiresAt) - nowMs) / 86_400_000);
  return days <= 0 ? "ends today" : days === 1 ? "ends in 1 day" : `ends in ${days} days`;
}

function Accepted() {
  const { data, error } = useJson<FleetAcceptance[]>("/api/v1/client-posture/fleet/acceptances");
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Risks a person accepted, and checks marked not applicable, across all clients. The ones about to run out come first; those with no end date are last.</p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {!data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && data.length === 0 && <p className="text-sm text-slate-400">Nothing is accepted.</p>}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="fleet-accepted">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">Client</th>
              <th className="pr-3">Check</th>
              <th className="pr-3">Why</th>
              <th>Until</th>
            </tr>
          </thead>
          <tbody>
            {data.map((a) => (
              <tr key={`${a.client_id}:${a.key}`} className="border-t border-slate-800 text-slate-300">
                <td className="py-1 pr-3">
                  <Link href={clientHref(a.client_id)} className="text-sky-300 hover:underline">
                    {a.client_name}
                  </Link>
                </td>
                <td className="pr-3">{a.key.replace(/_/g, " ")}</td>
                <td className="pr-3">{a.reason}</td>
                <td className={a.expires_at ? "text-amber-300" : "text-slate-500"}>{a.not_applicable ? "not applicable" : endsText(a.expires_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export interface SearchHit {
  client_id: string;
  client_name: string;
  source: string;
  key: string;
  status: string;
  evidence: string;
  matched_items: string[];
  matched_text: boolean;
  accepted: boolean;
}

function Search({ initialQ = "", onAsked }: { initialQ?: string; onAsked?: (q: string) => void }) {
  const [text, setText] = useState(initialQ);
  const [asked, setAsked] = useState(initialQ);
  const { data, error } = useJson<SearchHit[]>(asked.length >= 2 ? `/api/v1/client-posture/fleet/search?q=${encodeURIComponent(asked)}` : null);
  return (
    <div className="space-y-3">
      <form
        className="flex items-center gap-2 print:hidden"
        onSubmit={(e) => {
          e.preventDefault();
          setAsked(text.trim());
          onAsked?.(text.trim());
        }}
      >
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="A machine, an account or a word, for example SRV-02" aria-label="Search the checks" className="w-96 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200" />
        <button type="submit" className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200">
          Search
        </button>
      </form>
      <p className="text-sm text-slate-400">Looks in what every tool reported for every client: the evidence, the check name and the machines and accounts behind each check.</p>
      {asked.length > 0 && asked.length < 2 && <p className="text-sm text-slate-500">Type at least two characters.</p>}
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {asked.length >= 2 && !data && !error && <p className="text-sm text-slate-500">Searching…</p>}
      {data && data.length === 0 && <p className="text-sm text-slate-400">Nothing mentions that.</p>}
      {data && data.length > 0 && (
        <table className="w-full text-left text-sm" data-testid="fleet-search">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-3">Client</th>
              <th className="pr-3">Tool</th>
              <th className="pr-3">Status</th>
              <th>Found in</th>
            </tr>
          </thead>
          <tbody>
            {data.map((h) => {
              const st = STATUS_TEXT[h.status] ?? STATUS_TEXT.partly;
              return (
                <tr key={`${h.client_id}:${h.key}`} className="border-t border-slate-800 text-slate-300">
                  <td className="py-1 pr-3">
                    <Link href={clientHref(h.client_id)} className="text-sky-300 hover:underline">
                      {h.client_name}
                    </Link>
                  </td>
                  <td className="pr-3">{TOOL_CHECK_LABELS[h.source] ?? h.source}</td>
                  <td className={`pr-3 ${st.className}`}>{st.text}{h.accepted ? " (accepted)" : ""}</td>
                  <td className="text-xs text-slate-400">
                    {h.key.replace(/_/g, " ")}
                    {h.matched_items.length > 0 ? `: ${h.matched_items.join("; ")}` : h.matched_text ? `: ${h.evidence}` : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export interface ToolCard {
  source: string;
  checks: number;
  met: number;
  partly: number;
  not_met: number;
  clients_with_problems: number;
  percent_fine: number | null;
}

export interface Breakdown {
  score: number | null;
  lost: number;
  rows: { source: string; key: string; status: string; weight: number; points_lost: number }[];
}

/** "-33.3 points" for a row of the breakdown. */
export function pointsText(p: number): string {
  return `-${p.toFixed(1)} points`;
}

function Tools() {
  const [reload, setReload] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [weight, setWeight] = useState("2");
  const [open, setOpen] = useState<string | null>(null);
  const cards = useJson<ToolCard[]>("/api/v1/client-posture/fleet/tools", reload);
  const weights = useJson<{ key: string; weight: number }[]>("/api/v1/client-posture/fleet/weights", reload);
  const save = async (k: string, w: number) => {
    try {
      const res = await authFetch(`/api/v1/client-posture/fleet/weights/${encodeURIComponent(k)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ weight: w }) });
      if (!res.ok) throw new Error(`The API answered ${res.status}`);
      setProblem(null);
      setReload((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not save");
    }
  };
  return (
    <div className="space-y-6">
      {(cards.error || weights.error || problem) && <p role="alert" className="text-sm text-red-300">{cards.error ?? weights.error ?? problem}</p>}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">Which tool has the most problems</h2>
        <p className="text-sm text-slate-400">Each tool's checks across all clients, worst first. Accepted and not applicable checks are left out.</p>
        {!cards.data && !cards.error && <p className="text-sm text-slate-500">Loading…</p>}
        {cards.data && cards.data.length === 0 && <p className="text-sm text-slate-400">No tool has sent checks yet.</p>}
        {cards.data && cards.data.length > 0 && (
          <table className="w-full text-left text-sm" data-testid="fleet-tools">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-3">Tool</th>
                <th className="pr-3">Fine</th>
                <th className="pr-3">Problems</th>
                <th className="pr-3">Need attention</th>
                <th>Clients affected</th>
              </tr>
            </thead>
            <tbody>
              {cards.data.map((t) => (
                <tr key={t.source} className="border-t border-slate-800 text-slate-300">
                  <td className="py-1 pr-3">
                    <button type="button" aria-expanded={open === t.source} aria-label={`Show the checks of ${TOOL_CHECK_LABELS[t.source] ?? t.source}`} className="text-sky-300 hover:underline" onClick={() => setOpen(open === t.source ? null : t.source)}>
                      {TOOL_CHECK_LABELS[t.source] ?? t.source}
                    </button>
                  </td>
                  <td className="pr-3">{t.percent_fine === null ? "—" : `${t.percent_fine}%`}</td>
                  <td className={`pr-3 ${t.not_met > 0 ? "text-red-300" : ""}`}>{t.not_met}</td>
                  <td className={`pr-3 ${t.partly > 0 ? "text-amber-300" : ""}`}>{t.partly}</td>
                  <td>{t.clients_with_problems}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-slate-500">Click a tool to see its checks that are not fine, client by client.</p>
        {open ? (
          <div className="space-y-2 rounded border border-slate-800 p-3" data-testid="tool-checks">
            <h3 className="text-sm font-semibold text-slate-200">{TOOL_CHECK_LABELS[open] ?? open}: checks that are not fine</h3>
            <Board key={open} board={open} title={TOOL_CHECK_LABELS[open] ?? open} source={open} />
          </div>
        ) : null}
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-200">How much each check counts</h2>
        <p className="text-sm text-slate-400">Every check counts once towards a client&apos;s score unless you make it count more (up to 5 times). A weight applies to every client.</p>
        {weights.data && weights.data.length === 0 && <p className="text-sm text-slate-400">Every check counts once.</p>}
        {weights.data && weights.data.length > 0 && (
          <ul className="space-y-1 text-sm text-slate-300" data-testid="fleet-weights">
            {weights.data.map((w) => (
              <li key={w.key}>
                {w.key.replace(/_/g, " ")}: counts {w.weight} times{" "}
                <button type="button" className="text-xs text-slate-500 underline hover:text-slate-300 print:hidden" onClick={() => void save(w.key, 1)}>
                  Reset
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex flex-wrap items-center gap-2 print:hidden"
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim()) void save(key.trim(), Number(weight));
          }}
        >
          <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="Check key, for example ninjaone_antivirus" aria-label="Check key" className="w-80 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200" />
          <select value={weight} onChange={(e) => setWeight(e.target.value)} aria-label="Weight" className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm">
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                counts {n} {n === 1 ? "time" : "times"}
              </option>
            ))}
          </select>
          <button type="submit" className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200">
            Set weight
          </button>
        </form>
      </section>
    </div>
  );
}

export function FleetPosture() {
  const { data: boards } = useJson<BoardMeta>("/api/v1/client-posture/fleet/boards");
  const [tab, setTab] = useState<string>("worst");
  const [days, setDays] = useState(1);
  const [q, setQ] = useState("");
  const [views, setViews] = useState<SavedView[]>([]);
  const [applied, setApplied] = useState(0);
  useEffect(() => setViews(loadViews()), []);
  const change = (next: SavedView[]) => {
    setViews(next);
    storeViews(next);
  };
  const apply = (name: string) => {
    const v = views.find((x) => x.name === name);
    if (!v) return;
    setTab(v.tab);
    setDays(v.days ?? 1);
    setQ(v.q ?? "");
    setApplied((n) => n + 1);
  };
  const saveCurrent = () => {
    const name = window.prompt("Name this view");
    if (name === null || !name.trim()) return;
    change(addView(views, { name, tab, ...(tab === "changes" ? { days } : {}), ...(tab === "search" && q ? { q } : {}) }));
  };
  const tabs: [string, string][] = [["worst", "Worst clients"], ["changes", "What changed"], ["coverage", "Coverage"], ["accepted", "Accepted risks"], ["search", "Search"], ["tools", "Tools"], ...Object.entries(boards ?? {}).map(([k, v]) => [k, v.title] as [string, string])];
  return (
    <div className="space-y-4 p-6">
      <div>
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-xl font-semibold text-slate-100">Fleet posture</h1>
          <button type="button" onClick={() => window.print()} className="rounded border border-slate-600 px-3 py-1 text-sm text-slate-200 print:hidden">
            Print
          </button>
        </div>
        <p className="mt-1 text-sm text-slate-400">Every client&apos;s tool checks side by side: who needs attention first, what is about to lapse, and what changed.</p>
      </div>
      <div role="tablist" className="flex flex-wrap gap-2">
        {tabs.map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)} className={`rounded border px-3 py-1 text-sm ${tab === id ? "border-sky-500/60 text-sky-200" : "border-slate-700 text-slate-300"}`}>
            {label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm print:hidden">
        <label className="flex items-center gap-2 text-slate-300">
          Saved views
          <select value="" onChange={(e) => apply(e.target.value)} aria-label="Saved views" className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
            <option value="">{views.length === 0 ? "None saved yet" : "Open a view…"}</option>
            {views.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={saveCurrent} className="rounded border border-slate-600 px-3 py-1 text-slate-200">
          Save this view
        </button>
        {views.length > 0 && (
          <button
            type="button"
            onClick={() => {
              const name = window.prompt(`Remove which view? (${views.map((v) => v.name).join(", ")})`);
              if (name && views.some((v) => v.name === name.trim())) change(removeView(views, name.trim()));
            }}
            className="rounded border border-slate-700 px-3 py-1 text-slate-400"
          >
            Remove a view
          </button>
        )}
        <span className="text-xs text-slate-500">Kept in this browser only.</span>
      </div>
      {tab === "worst" ? <Worst /> : tab === "changes" ? <Changes key={`c${applied}`} initialDays={days} onDays={setDays} /> : tab === "coverage" ? <CoverageTab /> : tab === "accepted" ? <Accepted /> : tab === "search" ? <Search key={`s${applied}`} initialQ={q} onAsked={setQ} /> : tab === "tools" ? <Tools /> : <Board key={tab} board={tab} title={boards?.[tab]?.title ?? tab} />}
    </div>
  );
}
