'use client';

/**
 * The organisation's vCIO Risk Scoring settings: the points each severity weighs, the credit a partial or unknown answer earns, the critical-gap cap, the rating bands and the category
 * weights. One set for every client, kept here under Settings so only someone who may change settings can change how every client is scored. Saving scores every assessment again.
 */

import { useEffect, useState } from 'react';
import { apiErrorDetail } from '@/lib/api';
import { vcioRiskApi, type RiskSettings, type RiskSettingsAnswer } from '@/lib/vcioRisk';

const input = 'rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';
const SEVERITIES = ['Critical', 'High', 'Medium', 'Low'] as const;

export function VcioRiskSettings() {
  const [answer, setAnswer] = useState<RiskSettingsAnswer | null>(null);
  const [draft, setDraft] = useState<RiskSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');

  const show = (a: RiskSettingsAnswer) => {
    setAnswer(a);
    setDraft(a.settings);
  };
  useEffect(() => {
    vcioRiskApi
      .settings()
      .then(show)
      .catch((err) => setError(apiErrorDetail(err) ?? 'The settings could not be loaded.'));
  }, []);

  const save = async (settings: RiskSettings | Record<string, never>) => {
    setBusy(true);
    setError('');
    setSaved('');
    try {
      const a = await vcioRiskApi.saveSettings(settings);
      show(a);
      setSaved(`${a.using_defaults ? 'Back to the defaults' : 'Saved'}. ${a.rescored} assessment${a.rescored === 1 ? '' : 's'} scored again.`);
    } catch (err) {
      setError(apiErrorDetail(err) ?? 'The settings could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const num = (label: string, value: number, set: (n: number) => void, step = 1, max = 100) => (
    <label key={label} className="flex items-center justify-between gap-3 text-sm text-gray-200">
      <span>{label}</span>
      <input type="number" aria-label={label} value={value} min={0} max={max} step={step} onChange={(e) => set(Number(e.target.value))} className={`${input} w-24 text-right`} />
    </label>
  );

  return (
    <div className="space-y-4" data-testid="vcio-risk-settings">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">vCIO Risk Scoring</h1>
        <p className="mt-1 text-sm text-gray-400">
          How every client&apos;s Business Review is scored. One set for all clients: changing a value here changes every assessment&apos;s score, old and new.
          {answer ? (answer.using_defaults ? ' The defaults are in use.' : ' These differ from the defaults.') : ''}
        </p>
      </div>
      {error && (
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
          {saved}
        </p>
      )}
      {draft && (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <h2 className="text-sm font-semibold text-white">Severity points</h2>
            {SEVERITIES.map((s) => num(`${s} points`, draft.points[s], (n) => setDraft({ ...draft, points: { ...draft.points, [s]: n } })))}
            <h2 className="pt-2 text-sm font-semibold text-white">Answer credit (0 to 1)</h2>
            {num('Partial', draft.partial, (n) => setDraft({ ...draft, partial: n }), 0.05, 1)}
            {num('Unknown', draft.unknown, (n) => setDraft({ ...draft, unknown: n }), 0.05, 1)}
            {num('Alternative vendor', draft.alternative, (n) => setDraft({ ...draft, alternative: n }), 0.05, 1)}
            <h2 className="pt-2 text-sm font-semibold text-white">Critical-gap cap and ratings</h2>
            <label className="flex items-center justify-between gap-3 text-sm text-gray-200">
              <span>Cap a category that has a failed critical item</span>
              <input type="checkbox" aria-label="Apply the critical-gap cap" checked={draft.cap_on} onChange={(e) => setDraft({ ...draft, cap_on: e.target.checked })} />
            </label>
            {num('Cap the category at', draft.cap, (n) => setDraft({ ...draft, cap: n }), 0.01, 1)}
            {num('Green at or above', draft.green, (n) => setDraft({ ...draft, green: n }), 0.01, 1)}
            {num('Amber at or above', draft.amber, (n) => setDraft({ ...draft, amber: n }), 0.01, 1)}
          </section>
          <section className="space-y-2 rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <h2 className="text-sm font-semibold text-white">Category weights</h2>
            <p className="text-xs text-gray-500">Relative weights. A category with nothing answered drops out and the rest share the whole.</p>
            {Object.keys(draft.weights).map((c) => num(c, draft.weights[c] ?? 0, (n) => setDraft({ ...draft, weights: { ...draft.weights, [c]: n } })))}
            <div className="flex justify-end gap-2 pt-3">
              <button type="button" disabled={busy} onClick={() => void save({})} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800">
                Reset to defaults
              </button>
              <button type="button" disabled={busy} onClick={() => void save(draft)} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                Save settings
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
