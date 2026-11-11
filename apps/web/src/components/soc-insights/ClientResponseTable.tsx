'use client';

import useSWR from 'swr';
import { insightsApi, type ClientResponseTimes, type InsightsWindow } from '@/lib/api';

/** "45 min", "3.5 h", "2.1 days": the hours a response took, in the unit that reads best. */
export function hoursLabel(hours: number): string {
  if (!Number.isFinite(hours) || hours < 0) return '';
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours * 10) / 10} h`;
  return `${Math.round((hours / 24) * 10) / 10} days`;
}

/** The response times, or null when the server cannot say (a server without the route, a failed read): the table is extra detail and then simply is not shown. */
export async function loadResponseTimes(window: InsightsWindow): Promise<ClientResponseTimes | null> {
  try {
    return await insightsApi.getResponseTimes(window);
  } catch {
    return null;
  }
}

/** Response time per client for the chosen window, slowest first: the median, the slow end and how many alerts it rests on. Absent when the server cannot say or no client finished anything. */
export function ClientResponseTable({ window, onPick }: { window: InsightsWindow; onPick: (clientId: string) => void }) {
  const { data } = useSWR(['insights:response-times', window], () => loadResponseTimes(window), { shouldRetryOnError: false, revalidateOnFocus: false });
  if (!data || data.clients.length === 0) return null;
  return (
    <section aria-label="Response time per client" data-testid="client-response-table" className="mt-6">
      <h2 className="text-sm font-medium">Response time per client</h2>
      <p className="text-xs text-muted-foreground">How long alerts took from arriving to a person finishing them, for alerts that arrived in this window. Slowest client first. Press a name to look at that client alone.</p>
      <table className="mt-2 w-full text-left text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground">
            <th scope="col" className="py-1 pr-3">Client</th>
            <th scope="col" className="py-1 pr-3 text-right">Typical</th>
            <th scope="col" className="py-1 pr-3 text-right">Slowest tenth</th>
            <th scope="col" className="py-1 text-right">Alerts</th>
          </tr>
        </thead>
        <tbody>
          {data.clients.map((c) => (
            <tr key={c.client_id} className="border-t border-border">
              <td className="py-1.5 pr-3">
                <button type="button" onClick={() => onPick(c.client_id)} className="text-left text-blue-400 hover:underline">
                  {c.client_name}
                </button>
              </td>
              <td className="py-1.5 pr-3 text-right">{hoursLabel(c.median_hours)}</td>
              <td className="py-1.5 pr-3 text-right">{c.alerts >= 5 ? hoursLabel(c.p90_hours) : 'too few alerts'}</td>
              <td className="py-1.5 text-right">{c.alerts}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
