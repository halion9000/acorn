'use client';

export interface Slice {
  label: string;
  value: number;
  color: string;
}

/** The conic-gradient stops for the slices, in order, as a CSS background (pure); a total of zero is a plain grey ring. */
export function doughnutBackground(slices: Slice[]): string {
  const total = slices.reduce((a, s) => a + Math.max(0, s.value), 0);
  if (total <= 0) return 'conic-gradient(#4b5563 0 100%)';
  let at = 0;
  const stops = slices
    .filter((s) => s.value > 0)
    .map((s) => {
      const from = at;
      at += (s.value / total) * 100;
      return `${s.color} ${from.toFixed(2)}% ${at.toFixed(2)}%`;
    });
  return `conic-gradient(${stops.join(', ')})`;
}

/** A ring with a legend: each slice's name, count and share. */
export function Doughnut({ slices, testId }: { slices: Slice[]; testId?: string }) {
  const total = slices.reduce((a, s) => a + s.value, 0);
  return (
    <div className="flex flex-wrap items-center gap-6" data-testid={testId ?? 'doughnut'}>
      <div role="img" aria-label="Doughnut chart" className="relative h-44 w-44 shrink-0 rounded-full" style={{ background: doughnutBackground(slices) }}>
        <div className="absolute inset-6 flex items-center justify-center rounded-full text-center text-sm font-semibold" style={{ background: 'var(--metrics-card, #243236)' }}>
          {total}
        </div>
      </div>
      <ul className="space-y-1 text-sm">
        {slices.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-sm" style={{ background: s.color }} />
            <span>{s.label}</span>
            <span className="tabular-nums text-gray-400">
              {s.value} ({total > 0 ? Math.round((s.value / total) * 100) : 0}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
