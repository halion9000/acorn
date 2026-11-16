'use client';

/**
 * HubSpot automations: every automation that works with HubSpot lives here. The first copies the HaloPSA tickets of one category into HubSpot and keeps their status in step. CORE runs it and
 * reports each pass; this page shows the last one (from GET /api/v1/client-posture/sweeps/latest, source halo-hubspot). It is set up in CORE's HubSpot connector, where the HubSpot token is kept.
 */
import { useEffect, useState } from 'react';

import { type SweepRun, failureKind } from '@/components/settings/SourceHealth';
import { authFetch } from '@/lib/auth-session';

export const HALO_HUBSPOT_SOURCE = 'halo-hubspot';

const STATUS: Record<string, { text: string; className: string }> = {
  ok: { text: 'Running', className: 'text-emerald-300' },
  partly: { text: 'Running, with some problems', className: 'text-amber-300' },
  failed: { text: 'Failing', className: 'text-red-300' },
  stale: { text: 'Has not run for 48 hours', className: 'text-amber-300' },
};

const plural = (n: number, one: string, many: string): string => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** What the last pass did, in words (pure). The sweep's fields are used as: accounts = tickets in the category, sent = copied or moved, waiting = copied with no company, skipped = already in step. */
export function passSummary(r: SweepRun): string[] {
  return [
    `${plural(r.accounts, 'Halo ticket', 'Halo tickets')} in the category`,
    `${r.sent.toLocaleString()} copied or moved to another stage`,
    `${r.skipped.toLocaleString()} already in step, or opened before it was switched on`,
    ...(r.waiting > 0 ? [`${plural(r.waiting, 'ticket', 'tickets')} created without a company (no single HubSpot company has the client's name)`] : []),
    ...(r.failed > 0 ? [`${plural(r.failed, 'problem', 'problems')}`] : []),
  ];
}

export function HubSpotAutomations() {
  const [run, setRun] = useState<SweepRun | null | undefined>(undefined);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    let live = true;
    authFetch('/api/v1/client-posture/sweeps/latest')
      .then(async (res) => {
        if (!res.ok) throw new Error(`The sweep list answered ${res.status}`);
        return (await res.json()) as unknown;
      })
      .then((body) => {
        if (!live) return;
        const found = Array.isArray(body) ? (body as SweepRun[]).find((r) => r.source === HALO_HUBSPOT_SOURCE) : undefined;
        setRun(found ?? null);
      })
      .catch((e) => {
        if (!live) return;
        setRun(null);
        setProblem(e instanceof Error ? e.message : 'Could not read the status.');
      });
    return () => {
      live = false;
    };
  }, []);

  const status = run ? (STATUS[run.health] ?? STATUS.partly) : null;
  const kind = run?.first_error ? failureKind(run.first_error) : null;
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6" data-testid="hubspot-automations">
      <div>
        <h1 className="text-2xl font-bold text-white">HubSpot</h1>
        <p className="mt-1 text-sm text-gray-400">Automations that work with HubSpot. CORE runs them and reports here. They are set up in CORE, on its HubSpot connector, where the HubSpot token is kept.</p>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="halo-hubspot-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white">HaloPSA tickets to HubSpot</h2>
          {status ? <span className={`text-sm ${status.className}`}>{status.text}</span> : run === null ? <span className="text-sm text-gray-500">Not running</span> : null}
        </div>
        <p className="mt-1 text-sm text-gray-400">
          Tickets in one HaloPSA category are copied into HubSpot as tickets, linked to the HubSpot company with the client&apos;s name, and moved to HubSpot&apos;s closed stage when the Halo ticket is closed. One way only: nothing is written to HaloPSA.
        </p>
        {run === undefined && <p className="mt-3 text-sm text-gray-500">Loading...</p>}
        {run === null && (
          <div className="mt-3 text-sm text-gray-300" data-testid="halo-hubspot-off">
            <p>It has not reported yet. To turn it on, open CORE, then Connectors, then HubSpot:</p>
            <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-gray-400">
              <li>Paste the HubSpot private app token (scopes: tickets, and company read).</li>
              <li>Type the exact HaloPSA category to copy.</li>
              <li>Switch on &ldquo;Copy Halo tickets to HubSpot&rdquo;.</li>
            </ol>
            <p className="mt-1 text-gray-500">Only tickets opened after it is switched on are copied. The HubSpot playbook explains how to try it first without sending anything.</p>
          </div>
        )}
        {run && (
          <div className="mt-3 space-y-1 text-sm text-gray-300" data-testid="halo-hubspot-last">
            <p className="text-gray-500">Last checked {run.ran_at.slice(0, 16).replace('T', ' ')} (every ten minutes)</p>
            <ul className="list-disc pl-5">
              {passSummary(run).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {run.first_error ? (
              <p role="alert" className="text-red-300" data-testid="halo-hubspot-error">
                {run.first_error}
                {kind ? ` (${kind})` : ''}
              </p>
            ) : null}
          </div>
        )}
      </section>
      <p className="text-xs text-gray-500">More HubSpot automations will be listed here as they are built.</p>
    </div>
  );
}
