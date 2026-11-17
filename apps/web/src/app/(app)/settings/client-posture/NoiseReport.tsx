"use client";

/** Which rules raised the most alerts for this client that ended with nothing done (a false positive, or closed with no ticket, hidden or set aside as stale), with a suggestion where almost all of a rule's alerts were quiet. Reads GET /api/v1/alerts/noise. Describes only. */
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/auth-session";

export interface NoiseRule {
  rule: string;
  total: number;
  quiet: number;
  quiet_percent: number;
  with_ticket: number;
  suggestion: string | null;
}
interface Noise {
  days: number;
  total_alerts: number;
  rules: NoiseRule[];
}

const RANGES = [7, 30, 90] as const;

export function NoiseReport({ clientId }: { clientId: string }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [data, setData] = useState<Noise | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    authFetch(`/api/v1/alerts/noise?client_id=${encodeURIComponent(clientId)}&days=${days}`)
      .then(async (res) => {
        const body = res.ok ? ((await res.json()) as Partial<Noise>) : null;
        return { days, total_alerts: typeof body?.total_alerts === "number" ? body.total_alerts : 0, rules: Array.isArray(body?.rules) ? body.rules : [] } as Noise;
      })
      .catch(() => ({ days, total_alerts: 0, rules: [] }) as Noise)
      .then((d) => live && setData(d));
    return () => {
      live = false;
    };
  }, [clientId, days]);
  return (
    <section data-testid="noise-report" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm uppercase text-gray-500">Noisy rules</h3>
        <div className="flex gap-1 print:hidden" role="group" aria-label="Noise report period">
          {RANGES.map((d) => (
            <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)} className={`rounded border px-2 py-0.5 text-xs ${days === d ? "border-sky-500 text-sky-200" : "border-gray-700 text-gray-400"}`}>
              {d} days
            </button>
          ))}
        </div>
      </div>
      {data === null ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : data.rules.length === 0 ? (
        <p className="text-sm text-gray-400" data-testid="noise-empty">
          {data.total_alerts === 0 ? `No alerts in the last ${days} days.` : `None of the ${data.total_alerts} alerts of the last ${days} days ended with nothing done.`}
        </p>
      ) : (
        <>
          <p className="text-xs text-gray-500">Out of {data.total_alerts} alerts in the last {data.days} days, the rules whose alerts most often ended with nothing done.</p>
          <table className="w-full text-left text-sm" data-testid="noise-table">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="py-1 pr-3">Rule</th>
                <th className="pr-3 text-right">Alerts</th>
                <th className="pr-3 text-right">Nothing done</th>
                <th className="pr-3 text-right">Share</th>
                <th className="text-right">With a ticket</th>
              </tr>
            </thead>
            <tbody className="text-gray-300">
              {data.rules.map((r) => (
                <tr key={r.rule} className="border-t border-gray-800 align-top">
                  <td className="py-1 pr-3">
                    {r.rule}
                    {r.suggestion && <div className="text-xs text-amber-300">{r.suggestion}</div>}
                  </td>
                  <td className="pr-3 text-right tabular-nums">{r.total}</td>
                  <td className="pr-3 text-right tabular-nums">{r.quiet}</td>
                  <td className="pr-3 text-right tabular-nums">{r.quiet_percent}%</td>
                  <td className="text-right tabular-nums">{r.with_ticket}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
