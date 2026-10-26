"use client";

/**
 * A weekly update or a quarterly review for one client, written as an editable draft from what A.C.O.R.N holds (see summaryText.ts). It reads the score history, the checks that changed, the
 * comparison with other clients and, for the quarter, the tool counts; a part the person is not allowed to read, or that has no data, is simply left out. Nothing is sent: the draft is copied or printed.
 */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";
import { buildSummary, type SummaryChange } from "./summaryText";
import type { Posture } from "./ClientPosture";

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const res = await authFetch(url);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

interface History {
  first: number | null;
  last: number | null;
  change: number | null;
  rows?: unknown[];
}

export function ClientSummary({ posture, labelFor }: { posture: Posture; labelFor: (source: string, key: string) => string }) {
  const [days, setDays] = useState(7);
  const [text, setText] = useState("");
  const [state, setState] = useState<"loading" | "ready">("loading");

  useEffect(() => {
    let live = true;
    setState("loading");
    const id = encodeURIComponent(posture.client_id);
    void Promise.all([
      getJson<History>(`/api/v1/client-posture/${id}/score-history?days=${days}`),
      getJson<{ rows: (SummaryChange & { observed_at: string })[] }>(`/api/v1/client-posture/${id}/check-history?limit=500`),
      getJson<{ score: number | null; fleet_average: number | null; similar_average: number | null; similar_clients: number }>(`/api/v1/client-posture/${id}/compare`),
      days > 14 ? getJson<{ rows: { source: string; item: string; count: number; change?: number | null }[] }>(`/api/v1/billing/clients/${id}?days=${days}`) : Promise.resolve(null),
    ]).then(([history, changes, compare, counts]) => {
      if (!live) return;
      const checks = Object.entries(posture.tool_checks ?? {}).flatMap(([source, v]) => v.checks.map((c) => ({ source, key: c.key, status: c.status, accepted: !!c.accepted })));
      setText(
        buildSummary({
          name: posture.client_name ?? "This client",
          days,
          now: new Date(),
          checks,
          changes: (changes?.rows ?? []).filter((c) => Date.parse(c.observed_at) >= Date.now() - days * 86_400_000),
          history: history ? { first: history.first ?? null, last: history.last ?? null, change: history.change ?? null, days_with_data: history.rows?.length ?? 0 } : null,
          compare: compare && compare.fleet_average !== undefined ? compare : null,
          counts: counts?.rows ?? null,
          devices: posture.devices,
          identity: posture.identity,
          label: labelFor,
        }),
      );
      setState("ready");
    });
    return () => {
      live = false;
    };
  }, [posture, days, labelFor]);

  return (
    <section className="space-y-2" data-testid="client-summary">
      <h3 className="text-sm uppercase text-slate-500">Update for the client</h3>
      <div className="flex flex-wrap items-center gap-2 text-sm print:hidden">
        <label className="flex items-center gap-2 text-slate-300">
          Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Update period" className="rounded border border-slate-700 bg-slate-900 px-2 py-1">
            <option value={7}>Weekly update (7 days)</option>
            <option value={90}>Quarterly review (90 days)</option>
          </select>
        </label>
        <button type="button" className="rounded border border-slate-600 px-3 py-1 text-slate-200" onClick={() => void navigator.clipboard?.writeText(text)}>
          Copy
        </button>
        <span className="text-xs text-slate-500">A draft to edit. Nothing is sent.</span>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-slate-500">Writing the draft…</p>
      ) : (
        <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Draft update" rows={14} className="w-full rounded border border-slate-700 bg-slate-900 p-2 font-mono text-sm text-slate-200 print:border-0 print:bg-white print:text-black" />
      )}
    </section>
  );
}
