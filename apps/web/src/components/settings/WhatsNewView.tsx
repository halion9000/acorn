'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { USER_GUIDE } from '@/content/user-guide';
import { groupByDate, parseWhatsNew } from '@/lib/whats-new';

/** What was added lately, newest first: the entries of the guide that carry a dated "new" tag (see lib/whats-new.ts). Each links to its place in the guide. */
export function WhatsNewView() {
  const groups = useMemo(() => groupByDate(parseWhatsNew(USER_GUIDE)), []);
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="text-xl font-semibold text-gray-100">What&apos;s new</h1>
      <p className="mt-1 text-sm text-gray-400">
        Features added to A.C.O.R.N, newest first. This is built from the guide, so each entry opens the guide at the place that explains it.
      </p>
      {groups.length === 0 ? (
        <p className="mt-6 text-sm text-gray-500">Nothing is marked new in the guide yet.</p>
      ) : (
        <div className="mt-6 space-y-6">
          {groups.map((g) => (
            <section key={g.date} data-testid="whats-new-day">
              <h2 className="font-mono text-sm font-semibold text-gray-300">{g.date}</h2>
              <ul className="mt-2 space-y-2">
                {g.entries.map((e, i) => (
                  <li key={i} className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 text-sm text-gray-300">
                    <Link href={`/settings/guide#${e.sectionId}`} className="text-xs uppercase tracking-wide text-blue-300 hover:underline">
                      {e.section}
                    </Link>
                    <p className="mt-1 leading-relaxed">{e.text}</p>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
