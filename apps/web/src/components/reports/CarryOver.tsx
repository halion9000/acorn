'use client';

import { useCallback, useState } from 'react';
import Link from 'next/link';

import { alertsApi, casesApi } from '@/lib/api';
import { CARRY_LIST_CAP, ageLabel, byUrgency, carryOverText, type CarryOverData } from './carryOverList';

/** The statuses of a case that is still being worked. */
export const OPEN_CASE_STATUSES = 'new,triaged,investigating,contained';

/** Reads what is still open: the critical and high alerts, and the cases being worked. With a client, only that client's. */
export async function loadCarryOver(clientId: string): Promise<CarryOverData> {
  const scope = clientId ? { clientId } : {};
  const [critical, high, cases] = await Promise.all([
    alertsApi.list({ status: 'open', severity: 'critical', pageSize: CARRY_LIST_CAP, ...scope }),
    alertsApi.list({ status: 'open', severity: 'high', pageSize: CARRY_LIST_CAP, ...scope }),
    casesApi.list({ status: OPEN_CASE_STATUSES, scope: 'all', sort: 'work', limit: 200, ...scope }),
  ]);
  return {
    alerts: [...critical.alerts, ...high.alerts],
    alertTotal: critical.total + high.total,
    cases: cases.cases,
  };
}

/** Shift handover: what the next person inherits. Nothing is read until the button is pressed. */
export function CarryOver({ clientId }: { clientId: string }) {
  const [data, setData] = useState<CarryOverData | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [readAt, setReadAt] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(null);
    setCopied(false);
    try {
      setData(await loadCarryOver(clientId));
      setReadAt(Date.now());
    } catch {
      setProblem('The carry-over list could not be read. Try again.');
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  const copy = useCallback(async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(carryOverText(data, Date.now()));
      setCopied(true);
    } catch {
      setProblem('Copying was not allowed by the browser.');
    }
  }, [data]);

  const now = readAt;
  const alerts = data ? byUrgency(data.alerts).slice(0, CARRY_LIST_CAP) : [];
  const cases = data ? byUrgency(data.cases).slice(0, CARRY_LIST_CAP) : [];

  return (
    <section className="rounded-lg border border-gray-700 bg-gray-800 p-4" data-testid="carry-over">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">Carry over to the next shift</h3>
          <p className="text-xs text-gray-400">The critical and high alerts still open, and the cases still being worked.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={load} disabled={loading} className="rounded border border-gray-600 px-3 py-1 text-xs text-gray-100 hover:border-sky-500 disabled:opacity-50">
            {loading ? 'Reading…' : data ? 'Refresh' : 'Show what carries over'}
          </button>
          {data && (
            <button type="button" onClick={copy} className="rounded border border-gray-600 px-3 py-1 text-xs text-gray-100 hover:border-sky-500">
              {copied ? 'Copied' : 'Copy as text'}
            </button>
          )}
        </div>
      </div>
      {problem && (
        <p role="alert" className="mt-2 text-xs text-red-300">
          {problem}
        </p>
      )}
      {data && (
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-xs font-medium text-gray-300" data-testid="carry-alert-count">
              Critical and high alerts still open: {data.alertTotal}
            </p>
            <ul className="mt-1 space-y-1 text-xs text-gray-300">
              {alerts.map((a) => (
                <li key={a.id} data-testid="carry-alert">
                  <span className="uppercase text-gray-400">{a.severity}</span>{' '}
                  <Link href={`/alerts/${a.id}`} className="text-sky-300 hover:underline">
                    {a.title || 'Untitled alert'}
                  </Link>
                  {a.clientName ? ` (${a.clientName})` : ''}, open {ageLabel(a.createdAt, now)}, with {a.assignee || 'nobody'}
                </li>
              ))}
              {data.alertTotal > alerts.length && <li data-testid="carry-alert-more">and {data.alertTotal - alerts.length} more</li>}
              {data.alertTotal === 0 && <li>None.</li>}
            </ul>
          </div>
          <div>
            <p className="text-xs font-medium text-gray-300" data-testid="carry-case-count">
              Cases still open: {data.cases.length}
            </p>
            <ul className="mt-1 space-y-1 text-xs text-gray-300">
              {cases.map((c) => (
                <li key={c.id} data-testid="carry-case">
                  <span className="uppercase text-gray-400">{c.severity}</span>{' '}
                  <Link href={`/cases/${c.id}`} className="text-sky-300 hover:underline">
                    {c.caseNumber ? `${c.caseNumber} ` : ''}
                    {c.title || 'Untitled case'}
                  </Link>
                  {c.clientName ? ` (${c.clientName})` : ''}, {c.status.replace(/_/g, ' ')}, open {ageLabel(c.createdAt, now)}, with {c.assignee || 'nobody'}
                </li>
              ))}
              {data.cases.length > cases.length && <li>and {data.cases.length - cases.length} more</li>}
              {data.cases.length === 0 && <li>None.</li>}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
