'use client';

/** The risk heat map: the 5 by 5 grid for a chosen date, before or after treatment, and how the levels moved month by month. */

import { useEffect, useState } from 'react';
import { riskRegisterApi, type RiskHeatMapData } from '@/lib/api';

const LEVEL_CLASS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  high: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
  medium: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
};

/** The dates a person can pick: today, then the last day of each of the last twelve months (pure). */
export function asOfChoices(today: Date): { value: string; label: string }[] {
  const out = [{ value: '', label: 'Today' }];
  for (let i = 1; i <= 12; i++) {
    const last = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - i + 1, 0));
    const value = last.toISOString().slice(0, 10);
    out.push({ value, label: last.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }) + ' (end)' });
  }
  return out;
}

export function RiskHeatMap({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<'inherent' | 'residual'>('inherent');
  const [asOf, setAsOf] = useState('');
  const [map, setMap] = useState<RiskHeatMapData | null>(null);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    let live = true;
    setProblem('');
    void (async () => {
      try {
        const m = await riskRegisterApi.heatmap(clientId, kind, asOf);
        if (live && m) setMap(m);
      } catch {
        if (live) setProblem('Could not load the heat map.');
      }
    })();
    return () => {
      live = false;
    };
  }, [clientId, kind, asOf]);

  return (
    <section className="space-y-3" data-testid="risk-heatmap">
      <div className="flex flex-wrap items-end gap-3">
        <h2 className="text-lg font-semibold text-white">Heat map over time</h2>
        <label className="text-xs text-gray-400">
          Show
          <select aria-label="Which levels" value={kind} onChange={(e) => setKind(e.target.value as 'inherent' | 'residual')} className="ml-2 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100">
            <option value="inherent">Before treatment</option>
            <option value="residual">After treatment</option>
          </select>
        </label>
        <label className="text-xs text-gray-400">
          As of
          <select aria-label="As of" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="ml-2 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100">
            {asOfChoices(new Date()).map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {map && (
        <>
          <div className="inline-grid grid-cols-[auto_repeat(5,3.5rem)] gap-1 text-center text-xs" data-testid="heatmap-grid">
            {[5, 4, 3, 2, 1].map((l) => (
              <div key={l} className="contents">
                <span className="self-center pr-1 text-gray-500">{l}</span>
                {map.cells
                  .filter((c) => c.likelihood === l)
                  .map((c) => (
                    <span
                      key={c.impact}
                      title={c.titles.join(', ')}
                      data-testid={`heat-${c.likelihood}-${c.impact}`}
                      className={`flex h-12 items-center justify-center rounded border ${LEVEL_CLASS[c.level ?? 'low']}`}
                    >
                      {c.count > 0 ? c.count : ''}
                    </span>
                  ))}
              </div>
            ))}
            <span />
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n} className="text-gray-500">
                {n}
              </span>
            ))}
          </div>
          <p className="text-sm text-gray-300" data-testid="heatmap-summary">
            {map.total} risk{map.total === 1 ? '' : 's'} on {map.as_of}: {map.by_level.critical} critical, {map.by_level.high} high, {map.by_level.medium} medium, {map.by_level.low} low.
          </p>
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm" data-testid="heatmap-trend">
              <thead className="bg-gray-900/60 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Month end</th>
                  <th className="px-3 py-2">Risks</th>
                  <th className="px-3 py-2">Critical</th>
                  <th className="px-3 py-2">High</th>
                  <th className="px-3 py-2">Medium</th>
                  <th className="px-3 py-2">Low</th>
                </tr>
              </thead>
              <tbody>
                {map.trend.map((t) => (
                  <tr key={t.date} className="border-t border-gray-800">
                    <td className="px-3 py-1.5">{t.date}</td>
                    <td className="px-3 py-1.5">{t.total}</td>
                    <td className="px-3 py-1.5">{t.critical}</td>
                    <td className="px-3 py-1.5">{t.high}</td>
                    <td className="px-3 py-1.5">{t.medium}</td>
                    <td className="px-3 py-1.5">{t.low}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-500">Levels are kept from the day this was added (18 November 2026). Earlier dates show each risk at the levels it had then.</p>
        </>
      )}
    </section>
  );
}
