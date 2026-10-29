"use client";

/**
 * What CORE can do to client Microsoft 365 tenants through CIPP, read only: whether real actions are switched on, which clients are opted in, how many accounts are protected, the hourly cap, what each allowed
 * action does and how risky it is, and the last requests with their outcome. The rules are CORE's saved settings: nothing on this page can change one or run an action. Backed by GET /api/v1/cipp-actions.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { ago } from "@/lib/ago";

export interface ActionInfo {
  action: string;
  risk: "low" | "medium" | "high";
  reversible: boolean;
  summary: string;
}

export interface AuditEntry {
  at: string;
  action: string;
  client_id: string;
  user: string | null;
  actor: string | null;
  reason: string | null;
  result: "executed" | "dry_run" | "refused" | "failed";
  code: string | null;
  detail: string | null;
  would_refuse: string | null;
}

export interface ActionsReport {
  live: boolean;
  all_clients: boolean;
  clients: string[];
  protected_users: number;
  protected_domains: number;
  max_per_hour: number;
  actions: ActionInfo[];
  audit: AuditEntry[];
  /** Audit lines CORE could not write since it started. Absent from an older CORE. */
  audit_failures?: number;
}

export interface ActionsView {
  report: ActionsReport | null;
  received_at: string | null;
  client_names: Record<string, string>;
}

export const OUTCOMES: Record<AuditEntry["result"], { label: string; className: string }> = {
  executed: { label: "Executed", className: "bg-red-500/20 text-red-200" },
  dry_run: { label: "Dry run", className: "bg-slate-600/30 text-slate-300" },
  refused: { label: "Refused", className: "bg-amber-500/20 text-amber-200" },
  failed: { label: "Failed", className: "bg-red-500/20 text-red-300" },
};

const RISK_CLASS: Record<ActionInfo["risk"], string> = { low: "text-emerald-300", medium: "text-amber-300", high: "text-red-300" };

/** A client as the page names it: its name from the mapping when there is one, with the CIPP id after it; the id alone when not mapped. */
export function clientLabel(id: string, names: Record<string, string>): string {
  return names[id] ? `${names[id]} (${id})` : id;
}

/** The one-sentence state of real actions, the most important thing on the page. */
export function modeSentence(r: ActionsReport): string {
  if (!r.live) return "Real actions are OFF: every request CORE receives is a dry run, and nothing is sent to CIPP.";
  const who = r.all_clients ? "ALL clients" : r.clients.length === 0 ? "NO client (none is opted in, so every real request is refused)" : `${r.clients.length} opted-in client${r.clients.length === 1 ? "" : "s"}`;
  if (r.max_per_hour === 0) return `Real actions are ON for ${who}, but the hourly cap is 0, so every real request is refused.`;
  return `Real actions are ON for ${who}, at most ${r.max_per_hour} per client per hour.`;
}

/** What would happen if real actions were switched on, from the rules as they stand. */
export function wouldSentence(r: ActionsReport): string {
  const where = r.all_clients ? "any client" : r.clients.length === 0 ? "no client (none is opted in)" : `only the ${r.clients.length} opted-in client${r.clients.length === 1 ? "" : "s"}`;
  const prot = r.protected_users + r.protected_domains;
  return `Switched on, an action could run for ${where}, at most ${r.max_per_hour} per client per hour, and never on the ${prot} protected ${prot === 1 ? "account or domain" : "accounts and domains"}.`;
}

/** The note on an audit line: why a request was refused, or what CIPP said, or what a dry run would have met. */
export function noteFor(e: AuditEntry): string {
  if (e.result === "refused") return e.code ? `Refused: ${e.code.replace(/_/g, " ")}` : "Refused";
  if (e.result === "dry_run" && e.would_refuse) return `Would have been refused: ${e.would_refuse.replace(/_/g, " ")}`;
  return e.detail ?? "";
}

export function CippActions() {
  const [view, setView] = useState<ActionsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch("/api/v1/cipp-actions");
        if (!res.ok) throw new Error(res.status === 403 ? "You do not have access to this page." : `The API answered ${res.status}`);
        if (live) setView((await res.json()) as ActionsView);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <p role="alert" className="m-6 rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
        {error}
      </p>
    );
  }
  if (!view) return <p className="m-6 text-sm text-slate-500">Loading…</p>;
  const r = view.report;
  const names = view.client_names;
  const stale = view.received_at !== null && Date.now() - Date.parse(view.received_at) > 3 * 3_600_000;
  const rows = (r?.audit ?? []).filter((e) => !outcome || e.result === outcome);

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">CIPP actions</h1>
        <p className="mt-1 max-w-prose text-sm text-slate-400">
          What CORE can do to client Microsoft 365 tenants through CIPP, and what it has been asked to do. Read only: the rules are CORE&apos;s saved settings, and nothing here can change one or run an action.
        </p>
      </div>

      {!r ? (
        <p data-testid="no-report" className="rounded border border-slate-700 p-3 text-sm text-slate-400">
          CORE has not reported yet. It sends this once CIPP is connected and CORE is running.
        </p>
      ) : (
        <>
          <p data-testid="mode" className={`rounded border p-3 text-sm ${r.live ? "border-red-500/40 bg-red-500/10 text-red-200" : "border-slate-700 bg-slate-800/40 text-slate-200"}`}>
            {modeSentence(r)}
          </p>
          <p className="text-xs text-slate-500">
            CORE reported {ago(view.received_at)}.
            {stale && <span data-testid="stale" className="ml-1 text-amber-300">That is a while ago: CORE may not be running, so what is shown may be out of date.</span>}
          </p>

          {(r.audit_failures ?? 0) > 0 && (
            <p data-testid="audit-failures" role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
              CORE could not write {r.audit_failures} audit line{r.audit_failures === 1 ? "" : "s"} since it started, so an action may have been taken with no line below to show for it. Check the disk CORE writes to.
            </p>
          )}

          <section aria-label="Rules" className="space-y-1 text-sm text-slate-300">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Rules</h2>
            <p data-testid="would">{wouldSentence(r)}</p>
            <p data-testid="opted-in">
              Opted-in clients:{" "}
              {r.all_clients ? "all clients" : r.clients.length === 0 ? "none" : r.clients.map((c) => clientLabel(c, names)).join(", ")}
            </p>
            <p>
              Protected: {r.protected_users} account{r.protected_users === 1 ? "" : "s"} and {r.protected_domains} domain{r.protected_domains === 1 ? "" : "s"} are never touched, dry run or not.
            </p>
          </section>

          <section aria-label="Allowed actions">
            <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Allowed actions</h2>
            <table className="w-full text-left text-sm" data-testid="allowlist">
              <thead className="text-xs text-slate-500">
                <tr>
                  <th scope="col">Action</th>
                  <th scope="col">What it does</th>
                  <th scope="col">Risk</th>
                  <th scope="col">Can be undone</th>
                </tr>
              </thead>
              <tbody>
                {r.actions.map((a) => (
                  <tr key={a.action} className="border-t border-slate-800 align-top">
                    <td className="py-1.5 pr-3 font-mono text-xs">{a.action}</td>
                    <td className="pr-3 text-slate-300">{a.summary}</td>
                    <td className={`pr-3 ${RISK_CLASS[a.risk]}`}>{a.risk}</td>
                    <td className="text-slate-400">{a.reversible ? "in one step" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section aria-label="Recent requests">
            <div className="mb-1 flex items-center gap-3">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent requests</h2>
              <select aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs">
                <option value="">All outcomes</option>
                {(Object.keys(OUTCOMES) as AuditEntry["result"][]).map((k) => (
                  <option key={k} value={k}>
                    {OUTCOMES[k].label}
                  </option>
                ))}
              </select>
            </div>
            {rows.length === 0 ? (
              <p className="text-sm text-slate-500">{r.audit.length === 0 ? "CORE has not been asked to do anything yet." : "No request has that outcome."}</p>
            ) : (
              <table className="w-full text-left text-sm" data-testid="audit">
                <thead className="text-xs text-slate-500">
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Action</th>
                    <th scope="col">Client</th>
                    <th scope="col">Person</th>
                    <th scope="col">Asked by</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e, i) => (
                    <tr key={`${e.at}-${i}`} className="border-t border-slate-800 align-top">
                      <td className="py-1.5 pr-3 text-xs text-slate-400" suppressHydrationWarning>
                        {new Date(e.at).toLocaleString()}
                      </td>
                      <td className="pr-3 font-mono text-xs">{e.action}</td>
                      <td className="pr-3">{names[e.client_id] ?? e.client_id}</td>
                      <td className="pr-3 text-slate-300">{e.user ?? ""}</td>
                      <td className="pr-3 text-slate-400">{[e.actor, e.reason].filter(Boolean).join(": ")}</td>
                      <td className="pr-3">
                        <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${OUTCOMES[e.result].className}`}>{OUTCOMES[e.result].label}</span>
                      </td>
                      <td className="text-xs text-slate-400">{noteFor(e)}</td>
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
