'use client';

/**
 * Release the quarantined message a "user asked to release a quarantined message" alert is about. Shows who it was for and from whom, and a Release button that asks for a confirmation (a person decides
 * each time; nothing releases on its own). CORE then has CIPP release it; this panel follows the request until it says released or failed. A link in a ticket opens the alert with ``?release=1`` and this
 * panel scrolled into view. Shows nothing for an alert that is not about a quarantined message.
 */

import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import useSWR from 'swr';
import { alertsApi, type QuarantineInfo } from '@/lib/api';

const POLL_MS = 5000;

export function releaseStateText(info: QuarantineInfo): { text: string; tone: string } {
  switch (info.state) {
    case 'pending':
      return { text: 'Release requested: waiting for CORE to pick it up…', tone: 'text-blue-300' };
    case 'claimed':
      return { text: 'CORE is releasing it through CIPP…', tone: 'text-blue-300' };
    case 'done':
      return { text: info.message || 'Released.', tone: 'text-green-300' };
    case 'failed':
      return { text: `Not released: ${info.message || 'CORE did not say why.'}`, tone: 'text-red-300' };
    default:
      return { text: '', tone: '' };
  }
}

export function QuarantineRelease({ alertId }: { alertId: string }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLElement | null>(null);
  const { data, mutate } = useSWR(['alert-quarantine', alertId], () => alertsApi.quarantine(alertId), {
    revalidateOnFocus: false,
    refreshInterval: (d) => (d && (d.state === 'pending' || d.state === 'claimed') ? POLL_MS : 0),
  });

  useEffect(() => {
    if (data?.available && typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('release') === '1') {
      box.current?.scrollIntoView?.({ block: 'center' });
    }
  }, [data?.available]);

  if (!data || !data.available) return null;
  const state = releaseStateText(data);
  const waiting = data.state === 'pending' || data.state === 'claimed';

  async function release() {
    setBusy(true);
    try {
      await mutate(await alertsApi.releaseQuarantine(alertId), { revalidate: false });
      setAsking(false);
      toast.success('Release requested.');
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not ask for the release.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section ref={box} aria-label="Quarantined message" className="rounded-xl border border-amber-500/30 bg-gray-900/60 p-5" data-testid="quarantine-release">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-amber-300">Quarantined message</h3>
      <p className="text-sm text-gray-200">
        {data.recipient ? <>Held for <span className="font-medium">{data.recipient}</span></> : 'A message is held'}
        {data.sender ? <> from <span className="font-medium">{data.sender}</span></> : null}
        {data.kind ? <span className="text-gray-400"> (held as {data.kind})</span> : null}.
      </p>
      {state.text ? (
        <p className={`mt-2 text-sm ${state.tone}`} data-testid="release-state">
          {state.text}
        </p>
      ) : null}
      {data.state !== 'done' && !waiting ? (
        asking ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-gray-300">
            <span>Only release it if you are sure it is safe: it goes to everyone it was sent to, and the sender is not trusted afterwards.</span>
            <button type="button" disabled={busy} onClick={() => void release()} className="rounded border border-amber-500/50 px-3 py-1 text-amber-300 hover:bg-amber-500/10 disabled:opacity-50" aria-label="Confirm release">
              {busy ? 'Asking…' : 'Yes, release it'}
            </button>
            <button type="button" disabled={busy} onClick={() => setAsking(false)} className="text-gray-400 hover:text-gray-200">
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" onClick={() => setAsking(true)} className="mt-3 rounded border border-gray-600 px-3 py-1 text-sm text-gray-200 hover:bg-gray-800">
            {data.state === 'failed' ? 'Try releasing again…' : 'Release this message…'}
          </button>
        )
      ) : null}
    </section>
  );
}
