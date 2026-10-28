'use client';

import useSWR from 'swr';
import Link from 'next/link';
import { playbookDryRunsApi, type PlaybookDryRun } from '@/lib/api';

/**
 * Playbook dry runs: which playbooks WOULD have run for an alert, and what they would have done. NOTHING WAS RUN. The MSSP ticks the clients this is on for (the "Automated playbooks" column
 * on the MSSP dashboard); a playbook moves to real automation later, one at a time, after its dry runs have been checked here.
 */

/** The steps as one line: "enrich → notify → revoke session". */
export function stepsLine(steps: PlaybookDryRun['steps']): string {
  return steps.map((s) => s.type.replace(/_/g, ' ')).join(' → ');
}

function Item({ run, showAlert }: { run: PlaybookDryRun; showAlert: boolean }) {
  return (
    <li className="rounded-lg border border-gray-800/60 bg-gray-900/40 px-3 py-2 text-sm" data-testid="dry-run">
      <p className="font-medium text-gray-100">{run.playbook_name}</p>
      {showAlert ? (
        <p className="mt-0.5 text-xs text-gray-400">
          {run.client_name ? `${run.client_name} · ` : ''}
          <Link href={`/alerts/${run.alert_id}`} className="text-blue-400 hover:text-blue-300">
            {run.alert_title ?? 'Alert'}
          </Link>
        </p>
      ) : null}
      <p className="mt-1 text-xs text-gray-500">Matched on: {run.matched_on.join(', ')}</p>
      <p className="mt-1 text-xs text-gray-300">
        Would have: <span data-testid="dry-run-steps">{run.steps.length ? stepsLine(run.steps) : 'no steps'}</span>
      </p>
      <p className="mt-1 text-[11px] text-gray-600">{new Date(run.created_at).toLocaleString()}</p>
    </li>
  );
}

const NOTHING_RAN = 'Nothing was run. This shows what the playbook would have done.';

/** The section on an alert: renders nothing when no playbook would have run for it. */
export function AlertDryRunsSection({ alertId }: { alertId: string }) {
  const { data } = useSWR(['playbook-dry-runs', alertId], () => playbookDryRunsApi.list({ alertId, limit: 20 }), { revalidateOnFocus: false, shouldRetryOnError: false });
  const items = data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <section aria-label="Playbooks that would have run" className="space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-wider text-gray-500">Playbooks that would have run</h3>
      <p className="text-xs text-gray-500">{NOTHING_RAN}</p>
      <ul className="space-y-2">
        {items.map((r) => (
          <Item key={`${r.alert_id}:${r.playbook_id}`} run={r} showAlert={false} />
        ))}
      </ul>
    </section>
  );
}

/** The Playbooks page tab: the newest dry runs across this organization and its clients. */
export function DryRunsTab() {
  const { data, error, isLoading } = useSWR('playbook-dry-runs-recent', () => playbookDryRunsApi.list({ limit: 100 }), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (error) return <p className="text-sm text-red-300">Couldn&apos;t load the dry runs.</p>;
  if (isLoading || !data) return <p className="text-sm text-gray-500">Loading…</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-400">
        {NOTHING_RAN} It is on for the clients ticked in the &ldquo;Automated playbooks&rdquo; column of the MSSP dashboard; a playbook moves to real automation later, one at a time, after its dry runs have been checked here.
      </p>
      {data.items.length === 0 ? (
        <p className="text-sm text-gray-500" data-testid="no-dry-runs">
          No dry runs yet. They appear when an alert for a ticked client matches a playbook&apos;s trigger (its severity and one of its tags).
        </p>
      ) : (
        <ul className="space-y-2">
          {data.items.map((r) => (
            <Item key={`${r.alert_id}:${r.playbook_id}`} run={r} showAlert />
          ))}
        </ul>
      )}
    </div>
  );
}
