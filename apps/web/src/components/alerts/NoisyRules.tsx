'use client';

/**
 * The ten rules that raised the most alerts lately, with how many are still open and how many were closed as false positives. A rule that is mostly false positives is marked "worth hiding": a suggestion
 * only until someone presses Hide… on the row and confirms (every client, 30 days, audited); the Hide button on an alert hides one client or one device. Alerts already hidden or set aside as stale are not counted.
 */

import Link from 'next/link';
import { useState } from 'react';
import useSWR from 'swr';
import toast from 'react-hot-toast';
import { alertsApi, type NoisyRule } from '@/lib/api';
import { vendorLabel } from '@/components/mssp/ClientMapping';

/** The hide-for-all-clients button of a rule worth hiding. It asks first: it hides the rule for every client for 30 days and hides the open alerts of it now. */
function HideRule({ rule, onHidden }: { rule: NoisyRule; onHidden: () => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!rule.sample_alert_id) return null;
  const alertId = rule.sample_alert_id;
  async function hide() {
    setBusy(true);
    try {
      const out = await alertsApi.hideType({ alertId, scope: 'all', days: 30 });
      toast.success(`Hidden for 30 days for every client${typeof out.hidden_alerts === 'number' ? ` (${out.hidden_alerts} open alert${out.hidden_alerts === 1 ? '' : 's'} hidden now)` : ''}.`);
      setAsking(false);
      onHidden();
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : 'Could not hide that.');
    } finally {
      setBusy(false);
    }
  }
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="ml-2 text-xs text-gray-400 hover:text-gray-200" aria-label={`Hide ${rule.name}`}>
        Hide…
      </button>
    );
  }
  return (
    <span className="ml-2 inline-flex items-center gap-2 text-xs text-gray-300">
      Hide for every client for 30 days?
      <button type="button" disabled={busy} onClick={() => void hide()} className="rounded border border-amber-500/40 px-2 py-0.5 text-amber-300 hover:bg-amber-500/10 disabled:opacity-50" aria-label={`Confirm hide ${rule.name}`}>
        {busy ? 'Hiding…' : 'Hide it'}
      </button>
      <button type="button" disabled={busy} onClick={() => setAsking(false)} className="text-gray-500 hover:text-gray-300">
        Cancel
      </button>
    </span>
  );
}

export function NoisyRules() {
  const [days, setDays] = useState(30);
  const { data, error, isLoading, mutate } = useSWR(['noisy-rules', days], () => alertsApi.noisyRules(days), { revalidateOnFocus: false });
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="noisy-rules">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-gray-100">Noisiest rules</h2>
          <p className="text-xs text-gray-500">The rules that raised the most alerts, and how many of them were false positives. Hidden and stale alerts are not counted.</p>
        </div>
        <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-200">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>
      {isLoading ? <p className="mt-3 text-sm text-gray-500">Loading…</p> : null}
      {error ? <p className="mt-3 text-sm text-red-300">Could not load the report.</p> : null}
      {data && data.length === 0 ? <p className="mt-3 text-sm text-gray-500">No alerts in this period.</p> : null}
      {data && data.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="px-2 py-1">Rule</th>
                <th className="px-2 py-1">Tool</th>
                <th className="px-2 py-1 text-right">Alerts</th>
                <th className="px-2 py-1 text-right">Open</th>
                <th className="px-2 py-1 text-right">False positives</th>
                <th className="px-2 py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.map((r) => (
                <tr key={r.name}>
                  <td className="max-w-[26rem] break-words px-2 py-1.5 text-gray-100">
                    <Link href={`/alerts?status=all&q=${encodeURIComponent(r.name)}`} className="hover:text-blue-300 hover:underline">
                      {r.name}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-gray-400">{r.source ? vendorLabel(r.source) : '—'}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-gray-200">{r.total}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-gray-200">{r.open}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums text-gray-200">
                    {r.false_positives} <span className="text-gray-500">({Math.round(r.false_positive_rate * 100)}%)</span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">{r.suggest_hide ? <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">Worth hiding</span> : null}
                    {r.suggest_hide ? <HideRule rule={r} onHidden={() => void mutate()} /> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
