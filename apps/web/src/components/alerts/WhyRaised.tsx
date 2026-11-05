'use client';

/**
 * "Why was this raised": the tool, the rule, how sure it was and what it names, as the alert stores them. Closed until opened, and read only then, so an alert page does not wait on it.
 */

import { useState } from 'react';
import useSWR from 'swr';
import { alertsApi } from '@/lib/api';

export function WhyRaised({ alertId }: { alertId: string }) {
  const [open, setOpen] = useState(false);
  const { data, error, isLoading } = useSWR(open ? ['alert-why', alertId] : null, () => alertsApi.why(alertId), { revalidateOnFocus: false });
  return (
    <details className="rounded-xl border border-gray-800/60 bg-gray-900/60 p-5" data-testid="why-raised" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-gray-400">Why was this raised</summary>
      {open && isLoading ? <p className="mt-3 text-sm text-gray-500">Loading…</p> : null}
      {open && error ? <p className="mt-3 text-sm text-red-300">Could not load the reasons.</p> : null}
      {data && data.facts.length === 0 ? <p className="mt-3 text-sm text-gray-500">This alert records nothing about why it was raised.</p> : null}
      {data && data.facts.length > 0 ? (
        <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
          {data.facts.map((f, i) => (
            <div key={`${f.label}:${i}`} className="contents">
              <dt className="text-gray-500">{f.label}</dt>
              <dd className="min-w-0 break-words text-gray-200">{f.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </details>
  );
}
