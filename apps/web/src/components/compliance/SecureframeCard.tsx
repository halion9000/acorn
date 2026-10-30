'use client';

/**
 * Secureframe's control tests on the Compliance index: how many pass, which fail and who owns them, as CORE last read them (GET /api/v1/secureframe).
 * Shown for the organization's own compliance only, and not at all until Secureframe is connected in CORE and has been read once.
 */
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';

export interface SecureframeView {
  report: {
    tests: { total: number; enabled: number; passing: number; failing: number; not_evaluated: number; disabled: number };
    frameworks: { key: string; name: string | null; failing: number; passing: number }[];
    failing: { key: string | null; title: string; owner: string | null; failing_since: string | null; frameworks: string[]; domain: string | null; message: string | null }[];
    risks: number | null;
    policies: number | null;
  } | null;
  received_at: string | null;
  passing_percent: number | null;
  /** Percentage points the pass rate moved in the last 30 days; absent or null until there is a week of history. */
  change_30_days?: number | null;
}

async function read(): Promise<SecureframeView> {
  const res = await authFetch('/api/v1/secureframe');
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as SecureframeView;
}

/** How long a test has been failing, in whole days, or null when it is not known. */
export function failingDays(since: string | null, now: number = Date.now()): number | null {
  const t = since ? Date.parse(since) : NaN;
  return Number.isFinite(t) ? Math.max(0, Math.floor((now - t) / 86_400_000)) : null;
}

/** "Up 3.2 points in 30 days", "down 1 point in 30 days", "unchanged in 30 days"; null when the change is not known. */
export function changePhrase(change: number | null | undefined): string | null {
  if (change === null || change === undefined) return null;
  if (change === 0) return 'unchanged in 30 days';
  const size = Math.abs(change);
  return `${change > 0 ? 'up' : 'down'} ${size} ${size === 1 ? 'point' : 'points'} in 30 days`;
}

export function SecureframeCard() {
  const { data, error } = useSWR('secureframe', read, { revalidateOnFocus: false, shouldRetryOnError: false });
  // Not connected (or not read yet), or the page may not read it: nothing to show, and no noise about a tool that is not in use.
  if (error || !data || !data.report) return null;
  const { tests, frameworks, failing } = data.report;
  const pct = data.passing_percent;
  return (
    <section className="rounded-lg border border-gray-700 bg-gray-800 p-5" aria-label="Secureframe" data-testid="secureframe-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-white font-semibold text-base">Secureframe control tests</h2>
        <span className="text-xs text-gray-500">{data.received_at ? `Read ${new Date(data.received_at).toLocaleString()}` : ''}</span>
      </div>
      <p className="mt-1 text-sm text-gray-300">
        {pct === null ? 'No test has been evaluated yet.' : `${pct}% of evaluated tests pass`}: {tests.passing} passing, {tests.failing} failing
        {tests.not_evaluated ? `, ${tests.not_evaluated} not evaluated` : ''}
        {tests.disabled ? `, ${tests.disabled} disabled` : ''}.
        {data.report.risks !== null ? ` ${data.report.risks} risks` : ''}
        {data.report.policies !== null ? `${data.report.risks !== null ? ',' : ''} ${data.report.policies} policies` : ''}
        {data.report.risks !== null || data.report.policies !== null ? '.' : ''}
      </p>
      {changePhrase(data.change_30_days) && (
        <p className="mt-0.5 text-xs text-gray-400" data-testid="secureframe-change">
          Pass rate {changePhrase(data.change_30_days)}.
        </p>
      )}
      {pct !== null && (
        <div role="progressbar" aria-label="Secureframe tests passing" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-700">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
        </div>
      )}
      {frameworks.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2 text-xs" data-testid="secureframe-frameworks">
          {frameworks.map((f) => (
            <li key={f.key} className={`rounded-full border px-2 py-0.5 ${f.failing > 0 ? 'border-amber-500/40 text-amber-200' : 'border-emerald-500/40 text-emerald-200'}`}>
              {f.name ?? f.key}: {f.failing} failing of {f.failing + f.passing}
            </li>
          ))}
        </ul>
      )}
      {failing.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Failing the longest</h3>
          <ul className="space-y-1.5 text-sm" data-testid="secureframe-failing">
            {failing.slice(0, 10).map((t, i) => {
              const days = failingDays(t.failing_since);
              return (
                <li key={`${t.key ?? t.title}-${i}`} className="text-gray-200">
                  {t.title}
                  <span className="text-gray-500">
                    {' '}
                    · {t.owner ?? 'no owner'}
                    {days !== null ? ` · failing ${days} day${days === 1 ? '' : 's'}` : ''}
                    {t.frameworks.length > 0 ? ` · ${t.frameworks.join(', ')}` : ''}
                  </span>
                </li>
              );
            })}
          </ul>
          {failing.length > 10 && <p className="mt-1 text-xs text-gray-500">{failing.length - 10} more are in Secureframe.</p>}
        </div>
      )}
    </section>
  );
}
