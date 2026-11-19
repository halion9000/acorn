'use client';

/** Every shared interface piece on one page (/guide/ui), so the look can be checked in both themes in one place. */
import { useState } from 'react';

import { BarCell, EmptyState, PageHeader, Segmented, SkeletonRows, StatCard } from './kit';
import { formatCompact, formatDuration, formatMoney, formatPercent, marginTone } from './format';

export function UiShowcase() {
  const [period, setPeriod] = useState(3);
  return (
    <div className="space-y-8 p-6" data-testid="ui-showcase">
      <PageHeader
        title="Interface components"
        subtitle="The pieces every page is built from, in the current theme."
        about={<p>Switch the theme with the moon button in the top bar. Numbers use tabular figures, change is shown with an arrow and a word as well as a color, and every control has a visible focus.</p>}
        actions={<Segmented label="Period" value={period} onChange={setPeriod} options={[{ value: 1, label: 'Last month' }, { value: 3, label: 'Last 3 months' }, { value: 12, label: 'Last 12 months' }]} />}
      />
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Stat cards</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Tickets created" value={formatCompact(19754)} delta={8.2} note="6,585 a month" spark={[3, 5, 4, 7, 6, 9, 8]} />
          <StatCard label="First response" value={formatDuration(851)} delta={-12.5} upIsGood={false} note="on average" spark={[9, 8, 8, 7, 6, 6, 5]} />
          <StatCard label="Net margin" value={formatPercent(41.3)} delta={0} note="no change" />
          <StatCard label="Revenue" value={formatMoney(1234567)} loading />
        </div>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Numbers with a bar</h2>
        <table className="w-full max-w-xl text-sm">
          <thead className="text-xs text-gray-400">
            <tr>
              <th className="px-3 py-2 text-left">Client</th>
              <th className="px-3 py-2 text-right">Net margin</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800 text-gray-200">
            {[['Acme Dental', 58], ['Birch Law', 31], ['Cedar Group', 12]].map(([n, m]) => (
              <tr key={n}>
                <td className="px-3 py-1.5">{n}</td>
                <td className="px-3 py-1.5 text-right">
                  <BarCell value={m as number} max={100} text={formatPercent(m as number)} tone={marginTone(m as number)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">Loading and empty</h2>
        <SkeletonRows rows={3} cols={4} />
        <EmptyState title="Nothing has arrived yet" why="CORE sends this about once a day once the tool is connected in CORE." action={<button className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white">Check CORE status</button>} />
      </section>
    </div>
  );
}
