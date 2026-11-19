'use client';

/** The utilization colors of the Rewst Staff Metrics page: 95% and over red, 80% orange, 60% green, 40% blue, under 40% purple. */
export type UtilBand = 'red' | 'orange' | 'green' | 'blue' | 'purple';
export const UTIL_COLORS: Record<UtilBand, string> = { purple: '#7e57c2', blue: '#42a5f5', green: '#66bb6a', orange: '#ffa726', red: '#ef5350' };

export function utilColorBand(pct: number | null | undefined): UtilBand {
  const n = typeof pct === 'number' && Number.isFinite(pct) ? pct : 0;
  return n >= 95 ? 'red' : n >= 80 ? 'orange' : n >= 60 ? 'green' : n >= 40 ? 'blue' : 'purple';
}

/** A fill for a band: the color at 28% strength, as a bar or cell background. */
export function utilFill(pct: number | null | undefined, alpha = 0.28): string {
  const hex = UTIL_COLORS[utilColorBand(pct)].replace('#', '');
  const n = parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** The bars of utilization by week: each bar in its band's color with its percentage above it. */
export function UtilBars({ points }: { points: { label: string; value: number | null }[] }) {
  if (points.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const top = Math.max(100, ...points.map((p) => p.value ?? 0));
  return (
    <div data-testid="util-bars">
      <div className="flex items-end gap-2" style={{ height: 240 }}>
        {points.map((p) => (
          <div key={p.label} className="flex min-w-0 flex-1 flex-col items-center justify-end" style={{ height: '100%' }}>
            <span className="mb-1 whitespace-nowrap text-[11px] tabular-nums" style={{ color: '#eafcff' }}>
              {p.value === null ? '' : `${p.value.toFixed(2)}%`}
            </span>
            <div data-testid="util-bar" className="w-full rounded-t" style={{ height: `${((p.value ?? 0) / top) * 100}%`, background: utilFill(p.value), border: `2px solid ${UTIL_COLORS[utilColorBand(p.value)]}`, minHeight: p.value ? 2 : 0 }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-2 text-[11px]" style={{ color: 'var(--metrics-soft)' }}>
        {points.map((p) => (
          <span key={p.label} className="flex-1 text-center">
            {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** One person per row, one week per column, each cell a colored percentage. A week with no figure shows a dash. */
export function UtilMatrix({ weeks, rows }: { weeks: string[]; rows: { name: string; by_week: Record<string, number | null> }[] }) {
  if (rows.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  return (
    <div className="max-h-[34rem] overflow-auto" data-testid="util-matrix">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead className="sticky top-0 z-10" style={{ background: '#1f2f33' }}>
          <tr>
            <th className="sticky left-0 px-4 py-2 text-left font-semibold" style={{ background: '#1f2f33' }}>
              User Name
            </th>
            {weeks.map((w) => (
              <th key={w} className="px-3 py-2 text-center font-semibold">
                {`Week: ${w}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t border-gray-800">
              <td className="sticky left-0 whitespace-nowrap px-4 py-2 font-medium" style={{ background: '#243236' }}>
                {r.name}
              </td>
              {weeks.map((w) => {
                const v = r.by_week[w];
                return (
                  <td key={w} className="px-2 py-1.5 text-center">
                    {v === null || v === undefined ? (
                      <span className="text-gray-500">—</span>
                    ) : (
                      <span className="inline-block min-w-[5.5rem] rounded-md px-2 py-1 text-xs font-semibold tabular-nums" style={{ background: utilFill(v), color: '#fff', border: `1px solid ${UTIL_COLORS[utilColorBand(v)]}` }}>
                        {v.toFixed(2)}%
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
