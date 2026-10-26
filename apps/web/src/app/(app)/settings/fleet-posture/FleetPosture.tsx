"use client";

/**
 * Every client's tool checks side by side: who is worst, what is about to expire or lapse, who still runs Windows 10, which backups are failing, who has administrators without two-step sign-in, and what
 * changed lately. Read only. Backed by GET /api/v1/client-posture/fleet/summary, /fleet/boards/{board} and /fleet/changes.
 */
import { useEffect, useState } from "react";
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

function Worst() {
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
            <td className="pr-3">{c.score === null ? "—" : `${c.score}%`}</td>
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

function Board({ board, title }: { board: string; title: string }) {
  const { data, error } = useJson<{ rows: BoardRow[] }>(`/api/v1/client-posture/fleet/boards/${encodeURIComponent(board)}`);
  if (error) return <p role="alert" className="text-sm text-red-300">{error}</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (data.rows.length === 0) return <p className="text-sm text-slate-400">Nothing on the {title.toLowerCase()} board needs attention.</p>;
  return (
    <table className="w-full text-left text-sm" data-testid={`fleet-board-${board}`}>
      <thead className="text-xs uppercase text-slate-500">
        <tr>
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

function Changes() {
  const [days, setDays] = useState(1);
  const { data, error } = useJson<FleetChange[]>(`/api/v1/client-posture/fleet/changes?days=${days}`);
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm text-slate-300">
        Last
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-slate-700 bg-slate-900 px-2 py-1" aria-label="Days">
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

export function FleetPosture() {
  const { data: boards } = useJson<BoardMeta>("/api/v1/client-posture/fleet/boards");
  const [tab, setTab] = useState<string>("worst");
  const tabs: [string, string][] = [["worst", "Worst clients"], ["changes", "What changed"], ["coverage", "Coverage"], ["accepted", "Accepted risks"], ...Object.entries(boards ?? {}).map(([k, v]) => [k, v.title] as [string, string])];
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
      {tab === "worst" ? <Worst /> : tab === "changes" ? <Changes /> : tab === "coverage" ? <CoverageTab /> : tab === "accepted" ? <Accepted /> : <Board key={tab} board={tab} title={boards?.[tab]?.title ?? tab} />}
    </div>
  );
}
