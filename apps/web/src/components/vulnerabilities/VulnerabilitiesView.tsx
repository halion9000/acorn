'use client';

/**
 * Vulnerabilities in clients' software, operating systems, firmware and internet-facing addresses, as the tools report them (ThreatMate today; NinjaOne and Addigy as their checks are added).
 * It is a view onto alerts, not a second list: every row is an open alert of the "vulnerability" category and links to that alert in the complete alerts list, where it is worked like any other.
 */

import { useState } from 'react';
import Link from 'next/link';
import useSWR from 'swr';

import { ClientPicker } from '@/components/mssp/ClientPicker';
import { vendorLabel } from '@/components/mssp/ClientMapping';
import { alertsApi, type Alert } from '@/lib/api';
import { downloadCsv } from '@/lib/csv';
import { safeDistance } from '@/lib/safe-date';
import { targetWords } from '@/app/(app)/settings/client-posture/ToolChecks';
import { vulnerabilitiesCsvText } from './vulnerabilitiesCsv';
import { overTargetCount, targetStanding } from './vulnTarget';

const SEVERITY_TEXT: Record<string, string> = {
  critical: 'text-red-300 border-red-500/40 bg-red-500/10',
  high: 'text-orange-300 border-orange-500/40 bg-orange-500/10',
  medium: 'text-yellow-300 border-yellow-500/40 bg-yellow-500/10',
  low: 'text-blue-300 border-blue-500/40 bg-blue-500/10',
  info: 'text-gray-300 border-gray-600 bg-gray-800',
};

const RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

/** The tool an alert came from, in words: a check alert's tags carry it ("threatmate"), else the alert's own source. */
export function toolOf(a: Alert): string {
  const tool = (a.tags ?? []).find((t) => ['threatmate', 'ninjaone', 'addigy'].includes(t)) ?? a.source ?? '';
  return tool ? vendorLabel(tool) : 'Unknown tool';
}

/** How many open findings each client has, most first (pure). The client is the alert's own tenant, which is what the page's client filter takes. */
export function byClient(alerts: Alert[]): { id: string; name: string; count: number; worst: string }[] {
  const out = new Map<string, { id: string; name: string; count: number; worst: string }>();
  for (const a of alerts) {
    const id = a.tenantId ?? '';
    const row = out.get(id) ?? { id, name: a.clientName ?? 'This organisation', count: 0, worst: a.severity };
    row.count += 1;
    if ((RANK[a.severity] ?? 9) < (RANK[row.worst] ?? 9)) row.worst = a.severity;
    out.set(id, row);
  }
  return [...out.values()].sort((a, b) => (RANK[a.worst] ?? 9) - (RANK[b.worst] ?? 9) || b.count - a.count || a.name.localeCompare(b.name));
}

/** Worst first, then newest first (pure). */
export function sortFindings(alerts: Alert[]): Alert[] {
  return [...alerts].sort((a, b) => (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9) || (b.createdAt ?? '').localeCompare(a.createdAt ?? ''));
}

/** "Fix within 24 hours" under a finding, or "Past its 24 hours target" in red once it has been open longer; nothing for a severity with no target. */
export function TargetLine({ id, severity, since }: { id: string; severity: string; since?: string | null }) {
  const t = targetStanding(severity, since);
  if (!t) return null;
  return (
    <p className={`mt-0.5 text-[11px] ${t.over ? 'text-red-300' : 'text-gray-500'}`} data-testid={`vuln-target-${id}`}>
      {t.over ? 'Past its ' : 'Fix within '}
      {targetWords(t.hours)}
      {t.over ? ' target' : ''}
    </p>
  );
}

export function VulnerabilitiesView() {
  const [clientId, setClientId] = useState('');
  const [lateOnly, setLateOnly] = useState(false);
  const { data, error, isLoading } = useSWR(
    ['vulnerability-alerts', clientId],
    () => alertsApi.list({ category: 'vulnerability', status: 'open', pageSize: 200, ...(clientId ? { clientId } : {}) }),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const all = sortFindings(data?.alerts ?? []);
  const late = overTargetCount(all);
  const findings = lateOnly ? all.filter((a) => targetStanding(a.severity, a.createdAt)?.over) : all;
  const clients = byClient(findings);
  const counts = findings.reduce<Record<string, number>>((m, a) => ({ ...m, [a.severity]: (m[a.severity] ?? 0) + 1 }), {});

  return (
    <div className="space-y-6" data-testid="vulnerabilities">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Vulnerabilities</h1>
          <p className="mt-1 max-w-2xl text-sm text-gray-400">
            Software, operating-system, firmware and internet-facing vulnerabilities the connected tools report for each client. It opens on all clients together; pick one to narrow it, or press a client&apos;s name below. Each row is an alert: open it to work it with the rest of the alerts.
          </p>
        </div>
        <ClientPicker value={clientId} onChange={setClientId} label="Show" ownLabel="All clients" />
      </div>

      {error ? (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200" role="alert">
          The vulnerabilities could not be loaded: {error instanceof Error ? error.message : String(error)}
        </p>
      ) : null}
      {isLoading && !data ? <p className="text-sm text-gray-400">Loading…</p> : null}

      {data ? (
        findings.length === 0 ? (
          <p className="rounded-lg border border-gray-800 bg-gray-900/60 p-4 text-sm text-gray-400" data-testid="vulnerabilities-empty">
            No open vulnerability alerts. They appear here when a connected tool reports serious patching, end-of-life, firmware or exposure problems for a client.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-gray-300" data-testid="vulnerabilities-summary">
              {findings.length} open:{' '}
              {(['critical', 'high', 'medium', 'low'] as const)
                .filter((s) => counts[s])
                .map((s) => `${counts[s]} ${s}`)
                .join(' · ')}
              {late > 0 ? <span className="text-red-300" data-testid="vulnerabilities-late" title="Fix-time targets, from when the alert was raised: critical 4 hours, high 24 hours, medium 5 days, low 14 days."> · {late} past their fix target</span> : null}
            </p>
            {late > 0 ? (
              <label className="flex items-center gap-1 text-xs text-gray-300">
                <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> Past target only
              </label>
            ) : null}
            <button
              type="button"
              onClick={() => downloadCsv(`vulnerabilities-${new Date().toISOString().slice(0, 10)}.csv`, vulnerabilitiesCsvText(findings, toolOf))}
              className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800"
            >
              Export CSV
            </button>
            </div>
            {!clientId && clients.length > 1 ? (
              <div className="flex flex-wrap gap-2" data-testid="vulnerabilities-by-client">
                {clients.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setClientId(c.id)}
                    className={`rounded border px-2 py-1 text-xs ${SEVERITY_TEXT[c.worst] ?? SEVERITY_TEXT.info}`}
                    title={`Show only ${c.name}`}
                  >
                    {c.name}: {c.count}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-900 text-xs text-gray-500">
                  <tr>
                    <th scope="col" className="px-3 py-2">Severity</th>
                    <th scope="col" className="px-3 py-2">Client</th>
                    <th scope="col" className="px-3 py-2">Finding</th>
                    <th scope="col" className="px-3 py-2">Tool</th>
                    <th scope="col" className="px-3 py-2">Seen</th>
                    <th scope="col" className="px-3 py-2"><span className="sr-only">Alert</span></th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((a) => (
                    <tr key={a.id} className="border-t border-gray-800 align-top" data-testid={`vuln-${a.id}`}>
                      <td className="px-3 py-2">
                        <span className={`rounded border px-2 py-0.5 text-xs ${SEVERITY_TEXT[a.severity] ?? SEVERITY_TEXT.info}`}>{a.severity}</span>
                      </td>
                      <td className="px-3 py-2 text-gray-200">{a.clientName ?? 'This organisation'}</td>
                      <td className="px-3 py-2">
                        <p className="text-gray-100">{a.title}</p>
                        {a.description ? <p className="mt-0.5 text-xs text-gray-400">{a.description}</p> : null}
                        <TargetLine id={a.id} severity={a.severity} since={a.createdAt} />
                      </td>
                      <td className="px-3 py-2 text-gray-300">{toolOf(a)}</td>
                      <td className="px-3 py-2 text-xs text-gray-400" suppressHydrationWarning>{safeDistance(a.createdAt, { addSuffix: true })}</td>
                      <td className="px-3 py-2">
                        <Link href={`/alerts/${a.id}`} className="whitespace-nowrap text-sky-300 underline">Open alert</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      ) : null}
    </div>
  );
}
