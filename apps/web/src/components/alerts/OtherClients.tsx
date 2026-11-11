'use client';

import Link from 'next/link';
import useSWR from 'swr';
import { alertsApi, type AlertAtOtherClients } from '@/lib/api';

/** The one sentence at the top of the card, from counts only (pure). */
export function otherClientsText(o: AlertAtOtherClients): string {
  const clients = `${o.client_count} other client${o.client_count === 1 ? '' : 's'}`;
  const alerts = `${o.total} alert${o.total === 1 ? '' : 's'}`;
  return `The same alert was raised at ${clients} in the last ${o.window_hours} hours (${alerts}). It may be one campaign.`;
}

/** The same alert (same title) at the organization's other clients in the last day, each linking to its newest one. Shows nothing when there is none, for a client's own users, or when it cannot be read. */
export function OtherClients({ alertId }: { alertId: string }) {
  const { data } = useSWR(['alert-other-clients', alertId], () => alertsApi.otherClients(alertId), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!data || !Array.isArray(data.clients) || data.clients.length === 0) return null;
  const unlisted = data.client_count - data.clients.length;
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-gray-300" data-testid="other-clients">
      <div className="text-xs font-semibold uppercase text-gray-500">Seen at other clients</div>
      <p className="mt-1">{otherClientsText(data)}</p>
      <ul className="mt-1 space-y-0.5 text-xs">
        {data.clients.map((c) => (
          <li key={c.client_id} data-testid="other-client">
            {c.newest_alert_id ? (
              <Link href={`/alerts/${c.newest_alert_id}`} className="text-sky-300 hover:underline">
                {c.name}
              </Link>
            ) : (
              c.name
            )}
            : {c.count}
            {c.newest_at ? `, newest ${c.newest_at.slice(0, 16).replace('T', ' ')} UTC` : ''}
          </li>
        ))}
        {unlisted > 0 ? <li data-testid="other-client-more">and {unlisted} more</li> : null}
      </ul>
    </div>
  );
}
