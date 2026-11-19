'use client';

/**
 * Expand your coverage: for each framework that is off, how many of its controls the frameworks that are on already cover (from the topic crosswalk, a planning aid). Read only; turning a framework on is in the Overview.
 */
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { complianceDashboardApi, type FrameworkOverlapRow } from '@/lib/api';

/** "28 with NIST CSF, 24 with CIS IG1", biggest share first, or nothing when no framework is on (pure). */
export function byFrameworkText(by: Record<string, number>): string {
  return Object.entries(by)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, n]) => `${n} with ${name}`)
    .join(', ');
}

export function FrameworkOverlap({ clientId }: { clientId: string }) {
  const [data, setData] = useState<{ enabled: string[]; candidates: FrameworkOverlapRow[] } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await complianceDashboardApi.overlap(clientId);
        if (live) setData(r);
      } catch {
        if (live) setData(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId]);

  if (!data || data.candidates.length === 0) return null;
  const none = data.enabled.length === 0;

  return (
    <section className="space-y-3" aria-label="Expand your coverage" data-testid="framework-overlap">
      <div>
        <h2 className="text-lg font-semibold text-white">Expand your coverage</h2>
        <p className="text-sm text-gray-400">
          {none
            ? 'Turn a framework on first; this then shows how much of each other framework its work would already cover.'
            : 'How much of each framework that is off the ones that are on already cover. A planning aid from a topic crosswalk, not an auditor finding.'}{' '}
          <Link href={clientId ? `/compliance?client=${encodeURIComponent(clientId)}` : '/compliance'} className="text-blue-300 hover:underline">
            Turn frameworks on in the Overview
          </Link>
        </p>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {data.candidates.map((c) => (
          <li key={c.framework} className="rounded-lg border border-gray-700 bg-gray-800 p-4" data-testid="overlap-row">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-white">{c.name}</h3>
              <span className="text-xs text-gray-400">{c.total_controls} controls</span>
            </div>
            <p className="mt-1 text-sm text-gray-200">
              <span className="font-semibold">{c.overlapping_controls}</span> overlapping controls{none ? '' : ` (${c.percent_overlapping}%)`}
            </p>
            {Object.keys(c.by_framework).length > 0 ? <p className="text-xs text-gray-400">{byFrameworkText(c.by_framework)}</p> : null}
            {c.unmapped_controls > 0 ? <p className="text-xs text-gray-500">{c.unmapped_controls} controls are not mapped yet, so their overlap is not known.</p> : null}
            {c.shared_topics.length > 0 || c.new_topics.length > 0 ? (
              <button type="button" onClick={() => setOpen(open === c.framework ? null : c.framework)} aria-expanded={open === c.framework} className="mt-2 text-xs text-blue-300 hover:underline">
                {open === c.framework ? 'Hide topics' : 'Show topics'}
              </button>
            ) : null}
            {open === c.framework ? (
              <div className="mt-2 space-y-1 text-xs text-gray-300">
                {c.shared_topics.length > 0 ? <p>Already covered: {c.shared_topics.join(', ')}.</p> : null}
                {c.new_topics.length > 0 ? <p>New work: {c.new_topics.join(', ')}.</p> : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default FrameworkOverlap;
