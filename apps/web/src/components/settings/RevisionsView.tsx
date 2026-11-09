'use client';

import { REVISIONS, APP_VERSION } from '@/lib/revisions';

/** The list of revisions, newest first. Built from the project's history by scripts/gen_revisions.py; the newest number is the one shown at the foot of the sidebar. */
export function RevisionsView() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="text-xl font-semibold text-gray-100">Revisions</h1>
      <p className="mt-1 text-sm text-gray-400">
        Every revision of A.C.O.R.N so far, newest first. The current version is{' '}
        <span className="font-mono text-gray-200">v{APP_VERSION}</span>. Each revision is one week of work: what was built or changed, picked from that week&apos;s history.
      </p>
      <ol className="mt-6 space-y-4">
        {REVISIONS.map((r, i) => (
          <li key={r.version} className="rounded-xl border border-gray-800 bg-gray-900/60 p-5" data-testid="revision">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="font-mono text-base font-semibold text-gray-100">v{r.version}</h2>
              {i === 0 && <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-xs text-blue-300">Current</span>}
              <span className="text-xs text-gray-500">week of {r.weekOf}</span>
              <span className="text-xs text-gray-600">
                {r.commits} changes{r.fixes > 0 ? `, ${r.fixes} of them fixes or test updates` : ''}
              </span>
            </div>
            {r.changes.length > 0 && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-300">
                {r.changes.map((c, k) => (
                  <li key={k}>{c}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
