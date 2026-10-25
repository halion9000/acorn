'use client';

/**
 * How CORE's per-client sweeps are doing, from the last pass each one reported: when it ran, how many clients it reached, how many it could not, and why. A sweep that has not run for 48 hours is
 * marked stale whatever its last result was. Backed by GET /api/v1/client-posture/sweeps/latest.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';
import { TOOL_CHECK_LABELS } from './ClientPosture';

export interface SweepRun {
  source: string;
  title: string;
  ran_at: string;
  accounts: number;
  sent: number;
  failed: number;
  waiting: number;
  skipped: number;
  first_error: string;
  health: 'ok' | 'partly' | 'failed' | 'stale' | string;
}

const HEALTH: Record<string, { text: string; className: string }> = {
  ok: { text: 'Reaching A.C.O.R.N', className: 'text-emerald-300' },
  partly: { text: 'Some clients failed', className: 'text-amber-300' },
  failed: { text: 'Failing', className: 'text-red-300' },
  stale: { text: 'Not run for 48 hours', className: 'text-amber-300' },
};

/**
 * What kind of trouble a sweep's first error describes, in words that say who to look at: A.C.O.R.N or the network (nothing could be sent), the tool's own key, the tool slowing CORE down, or the tool being
 * slow. Anything else is shown as it is.
 */
export function failureKind(message: string): string | null {
  const m = message.toLowerCase();
  if (!m) return null;
  if (/refused the (api )?(key|token)|\b40[13]\b|unauthori[sz]ed|forbidden|can't read that/.test(m)) return "the tool refused the key";
  if (/slow down|\b429\b|rate limit/.test(m)) return "the tool is rate limiting CORE";
  if (/didn't answer|timed out|timeout|\b50[234]\b/.test(m)) return "the tool is slow or down";
  if (/fetch failed|econnrefused|couldn't reach|a\.c\.o\.r\.n refused/.test(m)) return "A.C.O.R.N could not be reached";
  return null;
}

/** The runs that need a look first: failing, then partly, then stale, then fine, each in the order given. */
export function sortRuns(runs: SweepRun[]): SweepRun[] {
  const rank: Record<string, number> = { failed: 0, partly: 1, stale: 2, ok: 3 };
  return [...runs].sort((a, b) => (rank[a.health] ?? 4) - (rank[b.health] ?? 4));
}

export function SourceHealth() {
  const [runs, setRuns] = useState<SweepRun[] | null>(null);
  useEffect(() => {
    let live = true;
    authFetch('/api/v1/client-posture/sweeps/latest')
      .then(async (res) => (res.ok ? ((await res.json()) as unknown) : null))
      .then((body) => {
        if (live) setRuns(Array.isArray(body) ? (body as SweepRun[]) : null);
      })
      .catch(() => {
        if (live) setRuns(null);
      });
    return () => {
      live = false;
    };
  }, []);
  if (!runs || runs.length === 0) return null;
  const sorted = sortRuns(runs);
  const bad = sorted.filter((r) => r.health !== 'ok').length;
  return (
    <details className="rounded border border-slate-800 p-3 text-sm print:hidden" data-testid="source-health" open={bad > 0}>
      <summary className="cursor-pointer text-slate-300">
        Data sources: {bad === 0 ? 'every sweep is reaching A.C.O.R.N' : `${bad} of ${runs.length} need a look`}
      </summary>
      <table className="mt-2 w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="pr-3">Tool</th>
            <th className="pr-3">Last pass</th>
            <th className="pr-3">Reached</th>
            <th className="pr-3">Waiting to be mapped</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const h = HEALTH[r.health] ?? HEALTH.partly;
            return (
              <tr key={r.source} data-testid={`sweep-${r.source}`} className="border-t border-slate-800 text-slate-300">
                <td className="py-1 pr-3">{TOOL_CHECK_LABELS[r.source] ?? r.title}</td>
                <td className="pr-3">{new Date(r.ran_at).toLocaleString()}</td>
                <td className="pr-3">
                  {r.sent} of {r.accounts}
                </td>
                <td className="pr-3">{r.waiting}</td>
                <td className={h.className}>
                  {h.text}
                  {r.first_error ? (
                    <span className="ml-1 text-slate-500">
                      ({failureKind(r.first_error) ? `${failureKind(r.first_error)}: ` : ""}
                      {r.first_error})
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
