'use client';

/**
 * Refresh data on a Metrics page: asks CORE to read the weekly staff, ticket and invoice facts and send them now (instead of at its next hourly round), then asks the page for its data every ten seconds until the data
 * held is newer than the press (at most fifteen minutes), telling the person what is going on.
 */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

/** What the line next to the button says (pure): nothing before the first press; while waiting, that CORE was asked; once the data is newer than the press, when it arrived. */
export function refreshLine(pressedAt: number | null, receivedAt: string | null | undefined, now: number, timedOut: boolean): string {
  if (pressedAt === null) return '';
  const at = receivedAt ? new Date(receivedAt) : null;
  if (at && at.getTime() >= pressedAt) return `Data refreshed at ${at.toLocaleTimeString()}.`;
  if (timedOut) return 'CORE has not finished reading yet (it can take ten minutes or more). Refresh the page later to see the new numbers.';
  return `Asked CORE to read everything again (${Math.max(0, Math.round((now - pressedAt) / 1000))}s ago). This takes a few minutes; the page updates by itself.`;
}

export function RefreshMetrics({ receivedAt, reload }: { receivedAt: string | null | undefined; reload: () => void }) {
  const [pressedAt, setPressedAt] = useState<number | null>(null);
  const [, setTick] = useState(0);
  const newer = pressedAt !== null && receivedAt ? new Date(receivedAt).getTime() >= pressedAt : false;
  const timedOut = pressedAt !== null && Date.now() - pressedAt > 15 * 60 * 1000;
  const watching = pressedAt !== null && !newer && !timedOut;
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => {
      setTick((n) => n + 1);
      reload();
    }, 10_000);
    return () => clearInterval(timer);
  }, [watching, reload]);
  const press = async (): Promise<void> => {
    const at = Date.now();
    try {
      const res = await authFetch('/api/v1/reports/metrics/refresh', { method: 'POST' });
      if (res.ok) setPressedAt(at);
    } catch {
      /* the page keeps what it has */
    }
  };
  return (
    <span className="flex items-center gap-2">
      <button type="button" className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-50" disabled={watching} aria-busy={watching} onClick={() => void press()}>
        {watching ? 'Refreshing…' : 'Refresh data'}
      </button>
      <span className="text-xs text-sky-300" role="status" data-testid="metrics-refresh">
        {refreshLine(pressedAt, receivedAt, Date.now(), timedOut)}
      </span>
    </span>
  );
}
