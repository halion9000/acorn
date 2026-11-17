'use client';

import Link from 'next/link';
import useSWR from 'swr';
import { alertsApi } from '@/lib/api';

const words = (s: string | null): string => (s ?? '').replace(/_/g, ' ');

/** Other alerts of the same client from the last 30 days that look like this one: the same rule or title, or the same host, user or address, each with why. Describes only; shows nothing when there are none. */
export function SimilarAlertsPanel({ alertId }: { alertId: string }) {
  const { data } = useSWR(['similar-alerts', alertId], () => alertsApi.similar(alertId), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!data || !Array.isArray(data.alerts) || data.alerts.length === 0) return null;
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-sm text-gray-300" data-testid="similar-alerts">
      <div className="text-xs font-semibold uppercase text-gray-500">Similar alerts, last {data.window_days} days</div>
      <ul className="mt-2 space-y-2">
        {data.alerts.map((a) => (
          <li key={a.id} data-testid="similar-alert">
            <Link href={`/alerts/${encodeURIComponent(a.id)}`} className="text-blue-300 hover:underline">
              {a.title || '(untitled)'}
            </Link>
            <span className="ml-2 text-xs text-gray-500">
              {words(a.severity)} · {words(a.status)}
              {a.created_at ? ` · ${a.created_at.slice(0, 10)}` : ''}
            </span>
            <div className="text-xs text-gray-400">{a.why.join(' · ')}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
