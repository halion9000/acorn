"use client";

/**
 * The script log: every script A.C.O.R.N asked CORE to run on a machine, newest first, and what came of it: ran, did not run (failed, or nobody collected it) or still waiting. The result CORE reported, or why
 * there is none, is on each line, with a link to the alert it was for.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { scriptRunsApi, type ScriptRunList } from "@/lib/api";

type Tab = "all" | "failed" | "done" | "waiting";
const TAB_LABEL: Record<Tab, string> = { all: "All", failed: "Did not run", done: "Ran", waiting: "Waiting" };
const STATE_LABEL: Record<string, string> = { done: "Ran", failed: "Failed", expired: "Never collected", pending: "Waiting for CORE", claimed: "Running" };
const STATE_CLASS: Record<string, string> = {
  done: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  failed: "border-red-500/40 bg-red-500/15 text-red-300",
  expired: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  pending: "border-gray-500/40 bg-gray-500/15 text-gray-300",
  claimed: "border-blue-500/40 bg-blue-500/15 text-blue-300",
};

export function ScriptLog() {
  const [tab, setTab] = useState<Tab>("all");
  const [data, setData] = useState<ScriptRunList | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await scriptRunsApi.list(tab === "all" ? "" : tab));
      setError(null);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Could not load the script log");
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const count = (t: Tab): number | undefined => (data ? (t === "all" ? data.done + data.failed + data.waiting : data[t]) : undefined);

  return (
    <section className="mx-auto max-w-4xl space-y-3 p-6 pt-0" data-testid="script-log">
      <h2 className="text-lg font-semibold">Script log</h2>
      <p className="text-sm text-gray-400">
        Every script CORE was asked to run in the last {data?.days ?? 30} days, by a person or by an auto-run rule, and what came of it. A script nobody collected within 30 minutes was never run: CORE was off or could not reach A.C.O.R.N.
      </p>
      <div role="tablist" className="flex flex-wrap items-center gap-1 border-b border-gray-800">
        {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-blue-500 text-white" : "text-gray-400 hover:text-gray-200"}`}>
            {TAB_LABEL[t]}
            {count(t) !== undefined ? ` (${count(t)})` : ""}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      {data === null && !error ? <p className="text-sm text-gray-500">Loading...</p> : null}
      {data !== null && data.items.length === 0 ? <p className="text-sm text-gray-500" data-testid="script-log-empty">No scripts here.</p> : null}
      {data !== null && data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm" data-testid="script-log-table">
            <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Script</th>
                <th className="px-3 py-2">Machine</th>
                <th className="px-3 py-2">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.items.map((r) => (
                <tr key={r.id} data-testid="script-log-row">
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-400">
                    {r.requested_at.slice(0, 16).replace("T", " ")}
                    <div className="text-gray-600">{r.by === "rule" ? "by a rule" : "by a person"}</div>
                  </td>
                  <td className="px-3 py-2 text-gray-200">
                    {r.script}
                    {r.alert_id ? (
                      <div className="text-xs">
                        <Link href={`/alerts/${r.alert_id}`} className="text-blue-300 hover:underline">
                          {r.alert_title || "the alert"}
                        </Link>
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-gray-300">
                    {r.device ?? "—"}
                    {r.client_name ? <div className="text-xs text-gray-500">{r.client_name}</div> : null}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded border px-1.5 py-0.5 text-xs ${STATE_CLASS[r.status] ?? STATE_CLASS.pending}`}>{STATE_LABEL[r.status] ?? r.status}</span>
                    {r.message ? <div className="mt-1 whitespace-pre-wrap break-words text-xs text-gray-400">{r.message}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {data !== null && data.total > data.items.length ? <p className="text-xs text-gray-500">Showing the newest {data.items.length} of {data.total}.</p> : null}
    </section>
  );
}
