"use client";

/**
 * "What changed in this client's configuration": the stored check history as a feed, for the last day up to the last year, with each row named added, worsened or improved and a filter for one kind.
 * Who made a change is not known here (that needs the Microsoft audit log); this says what changed and when A.C.O.R.N saw it.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

interface Row {
  key: string;
  source: string;
  status: string;
  previous_status: string | null;
  evidence: string;
  observed_at: string;
  change: "added" | "worsened" | "improved" | "changed";
}

export const PERIODS: { days: number; label: string }[] = [
  { days: 1, label: "Last day" },
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 365, label: "Last year" },
];
const KINDS = ["all", "added", "worsened", "improved"] as const;
type Kind = (typeof KINDS)[number];

const STATUS_WORDS: Record<string, string> = { met: "Met", partly: "Partly met", not_met: "Not met" };
const status = (s: string | null): string => (s === null ? "" : (STATUS_WORDS[s] ?? s));
const CHANGE_CLASS: Record<Row["change"], string> = {
  added: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  worsened: "border-red-500/40 bg-red-500/10 text-red-300",
  improved: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  changed: "border-gray-600 bg-gray-800 text-gray-300",
};

/** "Not met → Met" for a change, "Not met" for a check that appeared. */
export function transition(r: Pick<Row, "previous_status" | "status">): string {
  return r.previous_status === null ? status(r.status) : `${status(r.previous_status)} → ${status(r.status)}`;
}

export function ConfigChanges({ clientId, labelFor }: { clientId: string; labelFor: (source: string, key: string) => string }) {
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState<Kind>("all");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRows(null);
    setProblem(null);
    const q = new URLSearchParams({ days: String(days), limit: "500" });
    if (kind !== "all") q.set("change", kind);
    authFetch(`/api/v1/client-posture/${clientId}/check-history?${q.toString()}`)
      .then(async (res) => {
        if (!live) return;
        if (!res.ok) throw new Error(`The API answered ${res.status}`);
        const body = (await res.json()) as { rows?: Row[] } | null;
        setRows(Array.isArray(body?.rows) ? body.rows : []);
      })
      .catch((e) => live && setProblem(e instanceof Error ? e.message : "Could not load"));
    return () => {
      live = false;
    };
  }, [clientId, days, kind]);

  return (
    <section data-testid="config-changes" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm uppercase text-gray-500">What changed</h3>
        <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-100">
          {PERIODS.map((p) => (
            <option key={p.days} value={p.days}>
              {p.label}
            </option>
          ))}
        </select>
        <div role="group" aria-label="Kind of change" className="flex gap-1">
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={kind === k}
              onClick={() => setKind(k)}
              className={`rounded border px-2 py-0.5 text-xs capitalize ${kind === k ? "border-blue-500 bg-blue-500/20 text-blue-200" : "border-gray-700 text-gray-300 hover:bg-gray-800"}`}
            >
              {k}
            </button>
          ))}
        </div>
      </div>
      {problem && <p className="text-sm text-amber-300">{problem}</p>}
      {!problem && rows === null && <p className="text-sm text-gray-400">Loading…</p>}
      {rows !== null && rows.length === 0 && <p className="text-sm text-gray-400" data-testid="config-changes-empty">Nothing changed in this period.</p>}
      {rows !== null && rows.length > 0 && (
        <ul className="space-y-1" data-testid="config-changes-list">
          {rows.map((r, i) => (
            <li key={`${r.source}-${r.key}-${r.observed_at}-${i}`} className="rounded border border-gray-800 bg-gray-900/50 px-3 py-1.5 text-sm">
              <span className={`mr-2 rounded border px-1.5 py-0.5 text-[11px] ${CHANGE_CLASS[r.change]}`}>{r.change}</span>
              <span className="text-gray-100">{labelFor(r.source, r.key)}</span>
              <span className="ml-2 text-xs text-gray-400">{transition(r)}</span>
              <span className="ml-2 text-xs text-gray-500">{new Date(r.observed_at).toISOString().slice(0, 10)}</span>
              {r.evidence ? <p className="text-xs text-gray-500">{r.evidence}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
