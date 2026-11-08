'use client';

import useSWR from 'swr';
import { alertsApi, type EarlierOutcomes as Outcomes } from '@/lib/api';

const words = (s: string): string => s.replace(/_/g, ' ');

/** The one sentence this card is made of, from counts only (pure). */
export function outcomesText(o: Outcomes): string {
  if (!o.enough) return `Only ${o.total} earlier alert${o.total === 1 ? '' : 's'} of this kind for this client in the last ${o.window_days} days: too few to say what usually happens.`;
  const status = Object.entries(o.by_status ?? {}).map(([k, n]) => `${n} ${words(k)}`).join(', ');
  const parts = [`${o.total} earlier alerts of this kind for this client in the last ${o.window_days} days: ${status}.`];
  if (o.with_ticket) parts.push(`${o.with_ticket} had a ticket.`);
  if (o.median_hours_to_finish !== null && o.median_hours_to_finish !== undefined) parts.push(`Median time to finish ${o.median_hours_to_finish} hours (from ${o.timed}).`);
  return parts.join(' ');
}

/** What usually happened to earlier alerts of the same kind for this client. Counts only; it describes and never advises or acts. Shows nothing when it cannot be loaded. */
export function EarlierOutcomes({ alertId }: { alertId: string }) {
  const { data } = useSWR(['earlier-outcomes', alertId], () => alertsApi.earlierOutcomes(alertId), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!data || typeof data.total !== 'number' || data.total === 0) return null;
  const dispositions = Object.entries(data.by_disposition ?? {});
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-sm text-gray-300" data-testid="earlier-outcomes">
      <div className="text-xs font-semibold uppercase text-gray-500">What usually happens</div>
      <p className="mt-1">{outcomesText(data)}</p>
      {data.enough && dispositions.length > 0 ? <p className="mt-1 text-xs text-gray-500">How they were judged: {dispositions.map(([k, n]) => `${n} ${words(k)}`).join(', ')}.</p> : null}
    </div>
  );
}
