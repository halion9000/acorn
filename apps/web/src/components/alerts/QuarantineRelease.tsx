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

const MARKS: Record<string, { word: string; tone: string }> = {
  OK: { word: 'ok', tone: 'text-green-300' },
  '-': { word: 'info', tone: 'text-gray-400' },
  CHECK: { word: 'check', tone: 'text-amber-300' },
  BAD: { word: 'bad', tone: 'text-red-300' },
};

/** CORE's check text as lines: the advice first, then each finding with its mark ("[BAD] Sender checks: ...") (pure). */
export function checkLines(text: string): { advice: string; findings: { mark: string; word: string; tone: string; text: string }[] } {
  const [advice = '', ...rest] = text.split('\n');
  return {
    advice,
    findings: rest
      .filter((l) => l.trim() !== '')
      .map((l) => {
        const m = /^\[(OK|-|CHECK|BAD)\]\s*(.*)$/.exec(l);
        const mark = m?.[1] ?? '-';
        return { mark, ...MARKS[mark]!, text: m ? m[2]! : l };
      }),
  };
}

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
  const [allowAsking, setAllowAsking] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLElement | null>(null);
  const { data, mutate } = useSWR(['alert-quarantine', alertId], () => alertsApi.quarantine(alertId), {
    revalidateOnFocus: false,
    refreshInterval: (d) => (d && (d.state === 'pending' || d.state === 'claimed' || d.check_state === 'pending' || d.check_state === 'claimed' || d.allow_state === 'pending' || d.allow_state === 'claimed') ? POLL_MS : 0),
  });

  useEffect(() => {
    if (data?.available && typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('release') === '1') {
      box.current?.scrollIntoView?.({ block: 'center' });
    }
  }, [data?.available]);

  if (!data || !data.available) return null;
  const state = releaseStateText(data);
  const waiting = data.state === 'pending' || data.state === 'claimed';

  const checking = data.check_state === 'pending' || data.check_state === 'claimed';
  const looksBad = (data.check_text ?? '').startsWith('Looks malicious');
  const allowWaiting = data.allow_state === 'pending' || data.allow_state === 'claimed';
  async function allow() {
    setBusy(true);
    try {
      await mutate(await alertsApi.allowSender(alertId, looksBad && understood), { revalidate: true });
      setAllowAsking(false);
      setUnderstood(false);
      toast.success('Allow requested.');
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not ask for that.');
    } finally {
      setBusy(false);
    }
  }
  async function askCheck() {
    try {
      await mutate(await alertsApi.checkQuarantine(alertId), { revalidate: true });
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not ask for the check.');
    }
  }

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
      <div className="mt-3" data-testid="quarantine-check">
        {data.check_state === 'done' && data.check_text ? (
          <div className="space-y-1 text-sm">
            <p className="font-medium text-gray-100" data-testid="check-advice">
              {checkLines(data.check_text).advice}
            </p>
            <ul className="space-y-0.5">
              {checkLines(data.check_text).findings.map((f, i) => (
                <li key={i} className="flex gap-2 text-gray-300" data-testid="check-finding">
                  <span className={`w-12 shrink-0 text-xs uppercase ${f.tone}`}>{f.word}</span>
                  <span className="min-w-0 break-words">{f.text}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {data.check_state === 'failed' ? <p className="text-sm text-red-300">Could not check it: {data.check_text || 'CORE did not say why.'}</p> : null}
        {checking ? <p className="text-sm text-blue-300">CORE is looking into why it was held…</p> : null}
        {!checking && data.check_state !== undefined ? (
          <button type="button" onClick={() => void askCheck()} className="mt-1 text-xs text-gray-400 hover:text-gray-200">
            {data.check_state === 'none' ? 'Check why it was held' : 'Check again'}
          </button>
        ) : null}
      </div>
      {data.allow_state !== undefined ? (
        <div className="mt-3 text-sm" data-testid="allow-sender">
          {data.allow_state === 'done' ? <p className="text-green-300">{data.allow_message}</p> : null}
          {data.allow_state === 'failed' ? <p className="text-red-300">Not allowed: {data.allow_message || 'CORE did not say why.'}</p> : null}
          {allowWaiting ? <p className="text-blue-300">Allow requested: waiting for CORE…</p> : null}
          {data.allow_state !== 'done' && !allowWaiting && data.allow_possible === false && data.allow_blocked ? <p className="text-xs text-gray-500">{data.allow_blocked}</p> : null}
          {data.allow_state !== 'done' && !allowWaiting && data.allow_possible ? (
            allowAsking ? (
              <div className="space-y-2 text-gray-300">
                <p>
                  Allow <span className="font-medium">{data.allow_sender}</span> for this client? It lets this one address through the filter. Microsoft removes the entry after 45 days in which it is not needed. Releasing this message is separate.
                </p>
                {looksBad ? (
                  <label className="flex items-start gap-2 text-red-200">
                    <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} className="mt-1" />
                    <span>The check says this message looks malicious or fake. I still want to allow this sender.</span>
                  </label>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" disabled={busy || (looksBad && !understood)} onClick={() => void allow()} className="rounded border border-amber-500/50 px-3 py-1 text-amber-300 hover:bg-amber-500/10 disabled:opacity-50" aria-label="Confirm allow sender">
                    {busy ? 'Asking…' : 'Yes, allow this sender'}
                  </button>
                  <button type="button" disabled={busy} onClick={() => setAllowAsking(false)} className="text-gray-400 hover:text-gray-200">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" onClick={() => setAllowAsking(true)} className="text-xs text-gray-400 hover:text-gray-200">
                {data.allow_state === 'failed' ? 'Try allowing the sender again…' : 'Allow this sender… (removed after 45 days unused)'}
              </button>
            )
          ) : null}
        </div>
      ) : null}
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
