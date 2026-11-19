/**
 * One place for how numbers are written on every page (pure), so figures read the same everywhere: thousands separators, no trailing noise, a real minus sign, units spelled out, and "n/a" for a missing value
 * instead of an empty cell or a dash that could mean zero.
 */
const MINUS = '−';

export const NA = 'n/a';

const missing = (v: number | null | undefined): v is null | undefined => v === null || v === undefined || Number.isNaN(v);

/** 12345.6 as "12,346"; with ``digits`` decimals when given. A negative number uses a real minus sign. */
export function formatNumber(v: number | null | undefined, digits = 0): string {
  if (missing(v)) return NA;
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return v < 0 && Number(s.replace(/,/g, '')) !== 0 ? `${MINUS}${s}` : s;
}

/** 1234567 as "1.2M", 12500 as "12.5K", 950 as "950": for tiles where the exact number is not the point. */
export function formatCompact(v: number | null | undefined): string {
  if (missing(v)) return NA;
  const a = Math.abs(v);
  const sign = v < 0 ? MINUS : '';
  if (a >= 1_000_000_000) return `${sign}${(a / 1_000_000_000).toFixed(1).replace(/\.0$/, '')}B`;
  if (a >= 1_000_000) return `${sign}${(a / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (a >= 10_000) return `${sign}${(a / 1000).toFixed(1).replace(/\.0$/, '')}K`;
  return formatNumber(v);
}

/** 1234.5 as "$1,235"; whole dollars unless ``cents`` is set. Negative as "−$1,235". */
export function formatMoney(v: number | null | undefined, cents = false): string {
  if (missing(v)) return NA;
  const s = Math.abs(v).toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 });
  return v < 0 && s.replace(/[^0-9]/g, '').replace(/0/g, '') !== '' ? `${MINUS}${s}` : s;
}

/** 12.345 as "12.3%". The value is already a percent (12.3, not 0.123). */
export function formatPercent(v: number | null | undefined, digits = 1): string {
  if (missing(v)) return NA;
  return `${formatNumber(v, digits)}%`;
}

/** A change as "+12.3%" or "−5.0%" with a sign always shown; zero is "0.0%". */
export function formatDelta(v: number | null | undefined, digits = 1): string {
  if (missing(v)) return NA;
  const n = formatNumber(Math.abs(v), digits);
  return v > 0 && Number(n) !== 0 ? `+${n}%` : v < 0 && Number(n) !== 0 ? `${MINUS}${n}%` : `${formatNumber(0, digits)}%`;
}

/** 90 minutes as "1 h 30 min", 45 as "45 min", 1500 as "1 d 1 h": a length of time in the two biggest units. */
export function formatDuration(minutes: number | null | undefined): string {
  if (missing(minutes)) return NA;
  const m = Math.round(Math.abs(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

/** "3 minutes ago", "2 hours ago", "yesterday", "5 days ago", then the date; for a time shown beside its exact value in a tooltip. */
export function formatRelative(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return NA;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return NA;
  const s = Math.round((nowMs - t) / 1000);
  if (s < 0) return 'just now';
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`;
  const d = Math.floor(h / 24);
  if (d === 1) return 'yesterday';
  if (d < 30) return `${d} days ago`;
  return new Date(t).toISOString().slice(0, 10);
}

export type Tone = 'good' | 'bad' | 'neutral';

/** Which way a change reads: for most figures up is good, for costs, times and open items down is good (``upIsGood`` false). Zero or missing is neutral. */
export function deltaTone(delta: number | null | undefined, upIsGood = true): Tone {
  if (missing(delta) || delta === 0) return 'neutral';
  return (delta > 0) === upIsGood ? 'good' : 'bad';
}

/** A margin as a tone: at least ``good`` percent is good, below ``bad`` is bad, in between neutral. */
export function marginTone(percent: number | null | undefined, good = 40, bad = 20): Tone {
  if (missing(percent)) return 'neutral';
  return percent >= good ? 'good' : percent < bad ? 'bad' : 'neutral';
}
