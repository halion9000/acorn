'use client';

export interface AreaPoint {
  label: string;
  value: number;
}

/** A tidy top for an axis: the next 1, 2, 2.5, 5 or 10 times a power of ten at or above the value (at least 1). */
export function axisTop(max: number): number {
  if (!(max > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= max) return step * power;
  return 10 * power;
}

/** The smooth path through the points (Catmull-Rom turned into cubic curves), as an SVG path string (pure). */
export function smoothPath(xy: [number, number][]): string {
  if (xy.length === 0) return '';
  if (xy.length === 1) return `M${xy[0]![0]},${xy[0]![1]}`;
  let d = `M${xy[0]![0].toFixed(1)},${xy[0]![1].toFixed(1)}`;
  for (let i = 0; i < xy.length - 1; i++) {
    const p0 = xy[i - 1] ?? xy[i]!;
    const p1 = xy[i]!;
    const p2 = xy[i + 1]!;
    const p3 = xy[i + 2] ?? p2;
    const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

/** A smooth filled line with a dot on every point, a value axis and the labels along the bottom, as the Rewst Dialpad charts draw it. */
export function AreaChart({ points, color, testId }: { points: AreaPoint[]; color: string; testId?: string }) {
  if (points.length === 0) return <p className="text-sm text-gray-500">Nothing in this period.</p>;
  const width = 1000;
  const height = 260;
  const top = axisTop(Math.max(0, ...points.map((p) => p.value)));
  const x = (i: number) => (points.length === 1 ? width / 2 : (width / points.length) * (i + 0.5));
  const y = (v: number) => height - (v / top) * height;
  const xy = points.map((p, i) => [x(i), y(p.value)] as [number, number]);
  const line = smoothPath(xy);
  const area = `${line} L${x(points.length - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div role="img" aria-label={`Area chart by ${points.length} weeks`} data-testid={testId ?? 'area-chart'}>
      <div className="flex gap-2">
        <div className="relative w-9 shrink-0 text-right text-[11px] tabular-nums" style={{ height, color: 'var(--metrics-soft)' }}>
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 translate-y-1/2" style={{ bottom: `${t * 100}%` }}>
              {Math.round(top * t * 100) / 100}
            </span>
          ))}
        </div>
        <div className="relative min-w-0 flex-1" style={{ height }}>
          {ticks.map((t) => (
            <div key={t} className="pointer-events-none absolute left-0 right-0" style={{ bottom: `${t * 100}%`, borderTop: '1px solid var(--metrics-grid)' }} />
          ))}
          <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
            <path d={area} fill={color} fillOpacity={0.22} />
            <path d={line} fill="none" stroke={color} strokeWidth={3} vectorEffect="non-scaling-stroke" />
          </svg>
          {points.map((p, i) => (
            <span key={p.label} title={`${p.label}: ${p.value}`} className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(x(i) / width) * 100}%`, top: `${(y(p.value) / height) * 100}%`, background: color }} />
          ))}
        </div>
      </div>
      <div className="ml-11 mt-1 flex text-[11px]" style={{ color: 'var(--metrics-soft)' }}>
        {points.map((p) => (
          <span key={p.label} className="flex-1 text-center">
            {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}
