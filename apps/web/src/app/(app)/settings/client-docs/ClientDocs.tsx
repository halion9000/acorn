"use client";

/**
 * A client's documentation (IT Glue) in one search box: documents, runbooks, configurations, locations and password ENTRIES. CORE reads it once a day and A.C.O.R.N keeps the text; this page only searches it
 * (GET /api/v1/client-documents) and links back to the record in IT Glue. A password entry shows its name and user name and a link: the password itself is never held, and it is masked in IT Glue until a
 * person with access reveals it.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { ago } from "@/lib/ago";

export interface DocHit {
  client_id: string;
  client: string | null;
  kind: string;
  title: string;
  folder?: string | null;
  url?: string | null;
  snippet: string;
}

export interface DocSummary {
  client_id: string;
  client: string | null;
  kinds: Record<string, number>;
  refreshed_at: string | null;
}

export const KIND_LABELS: Record<string, string> = {
  document: "Document",
  asset: "Runbook or asset",
  configuration: "Configuration",
  location: "Location",
  password: "Password entry",
  ticket: "Ticket",
};

/** How long ago, in plain words. */
export function agoWords(iso: string | null, now: number = Date.now()): string {
  return ago(iso, { now, missing: "never" });
}

/** The totals line: how many records, for how many clients, and when the newest was refreshed. */
export function summaryLine(rows: DocSummary[], now: number = Date.now()): string {
  const records = rows.reduce((n, r) => n + Object.values(r.kinds).reduce((a, b) => a + b, 0), 0);
  const newest = rows.map((r) => r.refreshed_at).filter((x): x is string => !!x).sort().at(-1) ?? null;
  return `${records.toLocaleString()} records for ${rows.length} client${rows.length === 1 ? "" : "s"}; the newest was refreshed ${agoWords(newest, now)}.`;
}

const isHttps = (u: string | null | undefined): u is string => typeof u === "string" && u.startsWith("https://");

export function ClientDocs() {
  const [summary, setSummary] = useState<DocSummary[] | null>(null);
  // Set when the summary could not be read: that is not the same as "nothing has been read yet".
  const [summaryError, setSummaryError] = useState<string | null>(null);
  // Which search is the latest: a slower answer to an older one must not replace a newer answer.
  const latestSearch = useRef(0);
  const [q, setQ] = useState("");
  const [clientId, setClientId] = useState("");
  const [hits, setHits] = useState<DocHit[] | null>(null);
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await authFetch("/api/v1/client-documents/summary");
        if (!res.ok) throw new Error(res.status === 403 ? "You do not have access to the clients' documentation." : `The API answered ${res.status}`);
        const rows = (await res.json()) as DocSummary[];
        if (live) setSummary(Array.isArray(rows) ? rows : []);
      } catch (e) {
        if (live) {
          setSummary(null);
          setSummaryError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const search = useCallback(
    async (event?: { preventDefault: () => void }) => {
      event?.preventDefault();
      const text = q.trim();
      if (text.length < 2) return;
      const mine = ++latestSearch.current;
      setBusy(true);
      setError(null);
      try {
        const params = new URLSearchParams({ q: text, limit: "20" });
        if (clientId) params.set("client_id", clientId);
        const res = await authFetch(`/api/v1/client-documents?${params.toString()}`);
        if (!res.ok) throw new Error(res.status === 403 ? "You do not have access to the clients' documentation." : `The API answered ${res.status}`);
        const found = (await res.json()) as DocHit[];
        if (mine !== latestSearch.current) return; // a newer search has been asked since
        setHits(found);
        setAsked(text);
      } catch (e) {
        if (mine === latestSearch.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (mine === latestSearch.current) setBusy(false);
      }
    },
    [q, clientId],
  );

  const clients = [...(summary ?? [])].filter((r) => r.client).sort((a, b) => (a.client ?? "").localeCompare(b.client ?? ""));

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Client documentation</h1>
        <p className="mt-1 max-w-prose text-sm text-slate-400">
          What IT Glue says about each client: documents, runbooks, configurations, locations and password entries. Search by a word, a question, or a client&apos;s name. Password entries show a link, never the password.
        </p>
        {summaryError !== null && (
          <p data-testid="summary-error" role="alert" className="mt-1 text-xs text-red-300">
            Could not read what has been synced from IT Glue: {summaryError}
          </p>
        )}
        {summary !== null && (
          <p data-testid="docs-summary" className="mt-1 text-xs text-slate-500">
            {summary.length === 0
              ? "Nothing has been read from IT Glue yet. CORE reads it once a day after IT Glue is connected and each organization is mapped to a client."
              : summaryLine(summary)}
          </p>
        )}
      </div>

      <form onSubmit={search} className="flex flex-wrap items-center gap-2" role="search">
        <input
          type="search"
          aria-label="Search the documentation"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="onboarding guide, firewall, Microsoft admin login…"
          className="min-w-[18rem] flex-1 rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
        />
        {clients.length > 0 && (
          <select aria-label="Client" value={clientId} onChange={(e) => setClientId(e.target.value)} className="rounded border border-slate-600 bg-slate-900 px-2 py-2 text-sm">
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c.client_id} value={c.client_id}>
                {c.client}
              </option>
            ))}
          </select>
        )}
        <button type="submit" disabled={busy || q.trim().length < 2} className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </p>
      )}

      {hits !== null && !error && (
        <section aria-label="Results" data-testid="docs-results">
          <p className="mb-2 text-sm text-slate-400">
            {hits.length === 0 ? `Nothing in the documentation matches “${asked}”. It may not be documented, or not synced for that client yet.` : `${hits.length} best match${hits.length === 1 ? "" : "es"} for “${asked}”.`}
          </p>
          <ul className="space-y-3">
            {hits.map((h, i) => (
              <li key={`${h.client_id}-${h.url ?? h.title}-${i}`} className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-200">{KIND_LABELS[h.kind] ?? h.kind}</span>
                  {isHttps(h.url) ? (
                    <a href={h.url} target="_blank" rel="noreferrer" className="font-medium text-sky-300 hover:underline">
                      {h.title}
                    </a>
                  ) : (
                    <span className="font-medium">{h.title}</span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-slate-400">
                  {[h.client, h.folder].filter(Boolean).join(" · ")}
                </p>
                {h.kind === "password" && (
                  <p className="mt-1 text-xs text-amber-200">The password is masked in IT Glue. Open the link to reveal it if you have access.</p>
                )}
                {h.snippet && <p className="mt-1 whitespace-pre-line text-sm text-slate-300">{h.snippet}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
