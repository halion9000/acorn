/**
 * A ring split into coloured parts with a number and a caption in the middle, as on Secureframe's dashboard. Each part is a share of the total; a total of zero draws an empty grey ring. The parts are
 * listed beside it by the caller, so the picture is never the only place a number is.
 */
export interface DonutPart {
  value: number;
  color: string;
}

const R = 46;
const C = 2 * Math.PI * R;

/** The stroke length and start of each part around the ring (pure). */
export function arcs(parts: DonutPart[]): { color: string; length: number; offset: number }[] {
  const total = parts.reduce((sum, p) => sum + Math.max(0, p.value), 0);
  if (total <= 0) return [];
  let offset = 0;
  return parts
    .filter((p) => p.value > 0)
    .map((p) => {
      const length = (p.value / total) * C;
      const out = { color: p.color, length, offset };
      offset += length;
      return out;
    });
}

export function Donut({ parts, center, caption, label }: { parts: DonutPart[]; center: string; caption: string; label: string }) {
  const drawn = arcs(parts);
  return (
    <div className="relative h-28 w-28 shrink-0" role="img" aria-label={label}>
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <circle cx="60" cy="60" r={R} fill="none" stroke="currentColor" strokeWidth="12" className="text-gray-700" />
        {drawn.map((a, i) => (
          <circle key={i} cx="60" cy="60" r={R} fill="none" stroke={a.color} strokeWidth="12" strokeDasharray={`${a.length} ${C - a.length}`} strokeDashoffset={-a.offset} />
        ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold text-white">{center}</span>
        <span className="text-[10px] text-gray-400">{caption}</span>
      </div>
    </div>
  );
}
