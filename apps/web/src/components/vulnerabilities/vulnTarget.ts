/** How long a vulnerability alert may stay open before it counts as overdue, by severity (the same targets as a failing client check: critical 4 hours, high 24 hours, medium 5 days, low 14 days). Info has no clock. */
export const TARGET_HOURS: Record<string, number> = { critical: 4, high: 24, medium: 5 * 24, low: 14 * 24 };

export interface TargetStanding {
  hours: number;
  over: boolean;
}

/** The fix-time target of a finding and whether it has been open longer than that, or null for a severity with no target or a date that cannot be read (pure). */
export function targetStanding(severity: string, since: string | null | undefined, now: number = Date.now()): TargetStanding | null {
  const hours = TARGET_HOURS[severity];
  if (!hours || !since) return null;
  const start = Date.parse(since);
  if (Number.isNaN(start)) return null;
  return { hours, over: now - start > hours * 3_600_000 };
}

/** How many of the findings are past their target. */
export function overTargetCount(findings: { severity: string; createdAt?: string | null }[], now: number = Date.now()): number {
  return findings.filter((f) => targetStanding(f.severity, f.createdAt, now)?.over).length;
}

/** How many days there are to fix a vulnerability that is being used in attacks, counted from the day a tool first reported it at the client. Two weeks: the time CISA gives United States agencies for one newly put on its list. */
export const EXPLOITED_FIX_DAYS = 14;

export interface ExploitDue {
  /** The day it is due, as YYYY-MM-DD. */
  date: string;
  /** Whole days until that day (0 on the day itself), or how many days past it when ``over``. */
  days: number;
  over: boolean;
}

const DAY_MS = 86_400_000;

/** When a known-exploited vulnerability first seen on ``firstSeen`` is due to be fixed, counted in whole calendar days (UTC); null for a date that cannot be read (pure). */
export function exploitDue(firstSeen: string | null | undefined, now: number = Date.now()): ExploitDue | null {
  const start = firstSeen ? Date.parse(firstSeen) : NaN;
  if (Number.isNaN(start)) return null;
  const dueDay = Math.floor(start / DAY_MS) + EXPLOITED_FIX_DAYS;
  const left = dueDay - Math.floor(now / DAY_MS);
  return { date: new Date(dueDay * DAY_MS).toISOString().slice(0, 10), days: Math.abs(left), over: left < 0 };
}

/** "fix by 2026-11-24 (9 days left)", "fix by 2026-11-24 (today)" or "fix was due 2026-11-24 (3 days ago)". */
export function exploitDueText(due: ExploitDue): string {
  const days = `${due.days} ${due.days === 1 ? 'day' : 'days'}`;
  if (due.over) return `fix was due ${due.date} (${days} ago)`;
  return `fix by ${due.date} (${due.days === 0 ? 'today' : `${days} left`})`;
}
