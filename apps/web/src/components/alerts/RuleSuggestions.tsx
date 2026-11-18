'use client';

/**
 * Alerts > Hidden: hide rules proposed from what people always close as noise. For each client and alert type with five or more alerts closed as false positives and nearly nothing else, a row says so and offers
 * "Hide for this client" (no end date; it can be lifted from the list below). Nothing is hidden until the button is pressed and confirmed.
 */
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';

import { alertsApi, type RuleSuggestion } from '@/lib/api';

/** How a proposal reads (pure). */
export function suggestionText(s: Pick<RuleSuggestion, 'false_positives' | 'other_finished' | 'open_now'>): string {
  const fp = `${s.false_positives} closed as false positive`;
  const other = s.other_finished === 0 ? 'none closed any other way' : `${s.other_finished} closed another way`;
  return `${fp}, ${other}${s.open_now > 0 ? `, ${s.open_now} open now` : ''}`;
}

export function RuleSuggestions({ onHidden }: { onHidden?: () => void }) {
  const [rows, setRows] = useState<RuleSuggestion[] | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const out = await alertsApi.ruleSuggestions();
      setRows(Array.isArray(out) ? out : []);
    } catch {
      setRows([]);
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!rows || rows.length === 0) return null;

  const hide = async (s: RuleSuggestion) => {
    setBusy(true);
    try {
      const out = await alertsApi.hideType({ alertId: s.sample_alert_id, scope: 'client', days: null });
      toast.success(`Hidden for ${s.client_name}${typeof out.hidden_alerts === 'number' ? ` (${out.hidden_alerts} open alert${out.hidden_alerts === 1 ? '' : 's'} hidden now)` : ''}.`);
      setAsking(null);
      await load();
      onHidden?.();
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : 'Could not hide that.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="rule-suggestions">
      <h2 className="text-sm font-semibold text-gray-200">Proposed hide rules</h2>
      <p className="text-xs text-gray-500">Alert types a client&apos;s alerts of which are nearly always closed as false positives (the last 90 days). Nothing is hidden until you press the button and confirm; the rule can be lifted below.</p>
      <ul className="space-y-1 text-sm text-gray-200">
        {rows.map((s) => {
          const id = `${s.client_id}|${s.title}|${s.source ?? ''}`;
          return (
            <li key={id} className="flex flex-wrap items-center gap-2" data-testid="rule-suggestion">
              <span className="font-medium">{s.client_name}</span>
              <span>{s.title}</span>
              {s.source ? <span className="text-xs text-gray-500">({s.source})</span> : null}
              <span className="text-xs text-gray-400">{suggestionText(s)}</span>
              {asking === id ? (
                <span className="flex items-center gap-1 text-xs">
                  Hide this type for {s.client_name}?
                  <button type="button" disabled={busy} onClick={() => void hide(s)} className="rounded bg-blue-700 px-2 py-1 text-white hover:bg-blue-600 disabled:opacity-50">
                    Yes, hide
                  </button>
                  <button type="button" onClick={() => setAsking(null)} className="rounded border border-gray-700 px-2 py-1 hover:bg-gray-800">
                    Keep
                  </button>
                </span>
              ) : (
                <button type="button" aria-label={`Hide ${s.title} for ${s.client_name}`} onClick={() => setAsking(id)} className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800">
                  Hide for this client
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
