/**
 * "5 minutes ago", one way for the whole console.
 *
 * Eight screens each had their own copy, and they disagreed: some rounded, some cut off; one said "NaN days ago" for a date it could not read; they changed from hours to days at 24 hours, 48 hours or never.
 * This is the one rule. The time is cut down to whole units (59 minutes is "59 minutes", not "1 hour"), a time that cannot be read says what the caller chose instead of printing NaN, and a time in the future (a clock a little
 * ahead of the server's) reads as "just now" instead of a negative number.
 */

export interface AgoOptions {
  /** The moment to measure from (milliseconds); the current time by default. Tests pass one. */
  now?: number;
  /** "long": "5 minutes ago"; "short": "5m ago". */
  style?: 'long' | 'short';
  /** What to return when there is no time or it cannot be read. */
  missing?: string;
  /** Count seconds ("12s ago") once past the "just now" window, instead of going straight to minutes. */
  seconds?: boolean;
  /** How many seconds back still read as "just now": 120 for the long style, 60 for the short one, 1 when counting seconds. */
  justNowSeconds?: number;
  /** Past this many whole days, return the date itself instead of "N days ago". */
  dateAfterDays?: number;
}

type TimeInput = string | number | Date | null | undefined;

/** The time as milliseconds, or null when there is none or it cannot be read. */
export function toMillis(value: TimeInput): number | null {
  if (value === null || value === undefined || value === '') return null;
  const ms = value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

export function ago(value: TimeInput, options: AgoOptions = {}): string {
  const { now = Date.now(), style = 'long', missing = 'never', seconds = false, dateAfterDays } = options;
  const then = toMillis(value);
  if (then === null) return missing;
  const total = Math.max(0, Math.floor((now - then) / 1000));
  const minutes = Math.floor(total / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const short = style === 'short';
  if (dateAfterDays !== undefined && days >= dateAfterDays) return new Date(then).toLocaleDateString();
  const justNow = options.justNowSeconds ?? (seconds ? 1 : short ? 60 : 120);
  if (total < justNow) return 'just now';
  if (total < 60) {
    if (!seconds) return 'just now'; // under a minute and not counting seconds
    return short ? `${total}s ago` : `${total} second${total === 1 ? '' : 's'} ago`;
  }
  if (short) {
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 48) return `${hours}h ago`;
    return `${days}d ago`;
  }
  if (minutes < 120) return `${minutes} minutes ago`;
  if (hours < 48) return `${hours} hours ago`;
  return `${days} days ago`;
}

/** The same, for an age given in minutes (the API sends some as "minutes_ago"); null or not a number is "missing". */
export function agoMinutes(minutes: number | null | undefined, options: AgoOptions = {}): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return options.missing ?? 'never';
  const now = options.now ?? Date.now();
  return ago(now - minutes * 60_000, { ...options, now });
}

/** Whole days since a time, as "today", "1 day ago" or "12 days ago"; the fallback when the time cannot be read. */
export function daysAgo(value: TimeInput, options: { now?: number; missing?: string } = {}): string {
  const { now = Date.now(), missing = 'unknown date' } = options;
  const then = toMillis(value);
  if (then === null) return missing;
  const days = Math.max(0, Math.floor((now - then) / 86_400_000));
  return days === 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`;
}
