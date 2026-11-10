'use client';

/**
 * A world map shaded by how much mail was sent from each country, for the DMARC page. It is drawn from a country outline shipped with the app (Natural Earth, public domain, 110m;
 * `worldMapPaths.json`, one path per ISO country code), so it needs no map service and sends nothing anywhere. A country with failed mail is amber, one with only passing mail is blue;
 * the more mail, the stronger the shade. A country the outline does not have (a very small one) is left off the map, and the list beside it still names it.
 */
import world from './worldMapPaths.json';

export interface CountryCount {
  code: string;
  emails: number;
  failed: number;
}

const PATHS = (world as { paths: Record<string, string> }).paths;
const WIDTH = (world as { width: number }).width;
const HEIGHT = (world as { height: number }).height;

/** How strong a country's shade is, 0.25 to 1: by the logarithm of its mail, so one very busy country does not wash out the rest (pure). */
export function shade(emails: number, max: number): number {
  if (emails <= 0 || max <= 0) return 0;
  return 0.25 + 0.75 * (Math.log1p(emails) / Math.log1p(max));
}

/** The colour a country is drawn in: amber when any of its mail failed, blue when all passed, at the strength `shade` gives (pure). */
export function fillFor(c: CountryCount, max: number): { fill: string; opacity: number } {
  return { fill: c.failed > 0 ? '#f59e0b' : '#60a5fa', opacity: shade(c.emails, max) };
}

/** The codes the map can draw, and how many of the given countries it has to leave off (pure). */
export function drawable(countries: CountryCount[]): { shown: CountryCount[]; left: number } {
  const shown = countries.filter((c) => c.emails > 0 && PATHS[c.code.toUpperCase()] !== undefined);
  return { shown, left: countries.filter((c) => c.emails > 0).length - shown.length };
}

export default function CountryMap({
  countries,
  nameOf,
  selected,
  onSelect,
}: {
  countries: CountryCount[];
  nameOf: (code: string) => string;
  /** The country picked on the page (its outline is drawn brighter), and what a click on a country does. Without `onSelect` the map is a picture only. */
  selected?: string | null;
  onSelect?: (code: string) => void;
}) {
  const { shown, left } = drawable(countries);
  if (shown.length === 0) return null;
  const max = Math.max(...shown.map((c) => c.emails));
  const byCode = new Map(shown.map((c) => [c.code.toUpperCase(), c]));
  return (
    <div data-testid="country-map">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Map of where mail was sent from, shaded by how much each country sent" className="w-full rounded-lg border border-gray-800 bg-gray-950">
        {Object.entries(PATHS).map(([code, d]) => {
          const c = byCode.get(code);
          if (!c) return <path key={code} d={d} fill="#1f2937" stroke="#111827" strokeWidth={0.4} />;
          const { fill, opacity } = fillFor(c, max);
          return (
            <path
              key={code}
              d={d}
              fill={fill}
              fillOpacity={opacity}
              stroke={selected?.toUpperCase() === code ? '#f9fafb' : '#111827'}
              strokeWidth={selected?.toUpperCase() === code ? 1.2 : 0.4}
              data-testid="map-country"
              data-code={code}
              onClick={onSelect ? () => onSelect(code) : undefined}
              style={onSelect ? { cursor: 'pointer' } : undefined}
            >
              <title>{`${nameOf(code)}: ${c.emails.toLocaleString()} message${c.emails === 1 ? '' : 's'}, ${c.failed > 0 ? `${c.failed.toLocaleString()} failed` : 'all pass'}`}</title>
            </path>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-4 text-[11px] text-gray-400">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-blue-400" /> all mail passed
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-500" /> some failed
        </span>
        <span>Darker means more mail.</span>
        {left > 0 ? <span data-testid="map-left-off">{left} small {left === 1 ? 'country is' : 'countries are'} in the list only.</span> : null}
      </div>
    </div>
  );
}
