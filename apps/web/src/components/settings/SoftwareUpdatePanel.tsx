'use client';

import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';

import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Skeleton } from '@/components/ui/Skeleton';
import { useTenant } from '@/components/layout/TenantProvider';
import { platformUpdateApi, type PlatformUpdateStatus } from '@/lib/api';
import { PanelHeader, errorText } from './panel-parts';

const TITLE = 'Update A.C.O.R.N';
const DESCRIPTION = 'Install the latest version from GitHub. The update checks itself and goes back to the previous version if anything fails.';

/**
 * The Update button (server: platform_update.py). The API only leaves a request for the VM; the VM runs the update script and this screen shows its output. While the
 * update restarts A.C.O.R.N the status request fails for a minute or two, which is expected, so the screen keeps asking instead of showing an error.
 */
export function SoftwareUpdatePanel() {
  const { viewingOther, home } = useTenant();
  if (viewingOther) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p data-testid="viewing-other-notice" className="px-6 py-5 text-sm text-amber-200">
          This is a platform setting. Return to {home?.name ?? 'your tenant'} (the banner above has the button) and open this page again.
        </p>
      </div>
    );
  }
  return <Inner />;
}

/** The update script's own words for a run, in plain language. */
const HISTORY_STATUS: Record<string, string> = {
  ok: 'Updated',
  verify_ok: 'Checked: healthy',
  rollback_ok: 'Went back to the earlier version',
  rolled_back: 'Failed and went back to the earlier version',
  failed: 'Failed',
  verify_failed: 'Checked: not healthy',
  rollback_failed: 'Could not go back to the earlier version',
};
const HISTORY_MODE: Record<string, string> = { update: 'Update', force: 'Rebuild', verify: 'Health check', rollback: 'Roll back' };

function stateLabel(s: PlatformUpdateStatus): string {
  if (s.state === 'queued') return 'Waiting to start';
  if (s.state === 'running') return 'Updating…';
  if (s.last_run_ok === true) return 'Last update succeeded';
  if (s.last_run_ok === false) return 'Last update failed';
  return 'Ready';
}

function Inner() {
  const { data, error: loadError, isLoading, mutate } = useSWR('settings:software-update', () => platformUpdateApi.get(), {
    // Keep asking while an update is in flight: the API restarts partway through, so some answers fail and the next one succeeds.
    refreshInterval: (latest) => (!latest || latest.state === 'queued' || latest.state === 'running' ? 3000 : 0),
    shouldRetryOnError: true,
    errorRetryInterval: 3000,
  });
  const [asking, setAsking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      await mutate(await platformUpdateApi.start(), { revalidate: false });
      toast.success('Update requested');
    } catch (err) {
      setError(errorText(err, 'The update could not be requested.'));
    } finally {
      setStarting(false);
      setAsking(false);
    }
  };

  if (isLoading && !data) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <div className="px-6 py-5"><Skeleton className="h-24 w-full rounded-lg" /></div>
      </div>
    );
  }
  if (!data) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p role="alert" className="px-6 py-5 text-sm text-red-300">
          {loadError ? errorText(loadError, 'The update status could not be loaded.') : 'Waiting for A.C.O.R.N to answer…'}
        </p>
      </div>
    );
  }
  if (!data.available) {
    return (
      <div>
        <PanelHeader title={TITLE} description={DESCRIPTION} />
        <p data-testid="update-unavailable" className="px-6 py-5 text-sm text-gray-400">
          Updating from this screen is not set up on this A.C.O.R.N. It is available where A.C.O.R.N runs on the Azure server.
        </p>
      </div>
    );
  }
  const busy = data.state === 'queued' || data.state === 'running';
  return (
    <div>
      <PanelHeader title={TITLE} description={DESCRIPTION} />
      <div className="space-y-5 px-6 py-5">
        <section aria-label="Status" className="space-y-2 rounded-lg border border-gray-800 bg-gray-950/40 p-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span data-testid="update-state" className="rounded bg-gray-800 px-2 py-0.5 text-xs font-medium text-gray-200 ring-1 ring-gray-700">{stateLabel(data)}</span>
            {data.requested_by && busy ? <span className="text-gray-400">Requested by {data.requested_by}</span> : null}
            {data.last_run_at && !busy ? <span className="text-gray-500" suppressHydrationWarning>Last run {new Date(data.last_run_at).toLocaleString()}</span> : null}
          </div>
          {data.summary ? <p data-testid="update-summary" className="text-sm text-gray-300">{data.summary}</p> : null}
        </section>
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
        <div>
          <button
            type="button"
            disabled={busy || starting}
            onClick={() => setAsking(true)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Updating…' : 'Update A.C.O.R.N'}
          </button>
          {busy ? <p className="mt-2 text-xs text-gray-500">A.C.O.R.N restarts during the update, so this page may pause for a minute or two. It keeps checking.</p> : null}
        </div>
        {data.history && data.history.length > 0 ? (
          <table data-testid="update-history" className="w-full text-left text-xs text-gray-300">
            <caption className="pb-1 text-left text-sm text-gray-400">Earlier runs (times in UTC)</caption>
            <thead>
              <tr className="text-gray-500">
                <th scope="col">When</th>
                <th scope="col">What</th>
                <th scope="col">Result</th>
                <th scope="col">Version</th>
                <th scope="col">Took</th>
                <th scope="col">Asked by</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((h) => (
                <tr key={`${h.at}-${h.status}`}>
                  <td>{h.at.replace('T', ' ').replace('Z', '')}</td>
                  <td>{HISTORY_MODE[h.mode] ?? h.mode}</td>
                  <td className={h.ok ? 'text-emerald-300' : 'text-red-300'}>{HISTORY_STATUS[h.status] ?? h.status}</td>
                  <td className="font-mono">{h.commit ?? 'unknown'}</td>
                  <td>{tookLabel(h.seconds)}</td>
                  <td>{h.asked_by ?? 'on the server'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {data.log.length > 0 ? (
          <pre data-testid="update-log" aria-label="Update output" className="max-h-80 overflow-auto rounded-lg border border-gray-800 bg-black/40 p-3 text-xs text-gray-300">{data.log.join('\n')}</pre>
        ) : null}
      </div>
      <ConfirmDialog
        open={asking}
        title="Update A.C.O.R.N now?"
        message="A.C.O.R.N installs the latest version and restarts. It is unavailable for a few minutes, and goes back to the previous version by itself if the check after the update fails."
        confirmLabel="Update now"
        destructive={false}
        onConfirm={() => void start()}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}

/** "4 min 5 s" / "45 s" for the seconds a run took; a dash for a run recorded before the time was kept. */
export function tookLabel(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '–';
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}
