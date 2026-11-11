const DAY = 86_400_000;
const WEEK = 7 * DAY;

export interface TrendWeek {
  /** The Monday the week starts on, as YYYY-MM-DD (UTC). */
  weekStart: string;
  opened: number;
  closed: number;
}

/** The start (Monday 00:00 UTC) of the week a moment falls in. */
export function weekStartOf(ms: number): number {
  const d = new Date(ms);
  const midnight = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  const sinceMonday = (d.getUTCDay() + 6) % 7; // Monday = 0
  return midnight - sinceMonday * DAY;
}

/**
 * How many findings were raised and how many were closed in each of the last `weeks` weeks (the current week last), oldest first. A finding counts as opened in the week it was raised and as closed
 * in the week it was resolved; one with no resolve time, or a date that cannot be read, is not counted on that side. Weeks with nothing are still listed, so the run has no gaps. Pure.
 */
export function weeklyTrend(findings: { createdAt?: string | null; resolvedAt?: string | null }[], now: number = Date.now(), weeks = 8): TrendWeek[] {
  const last = weekStartOf(now);
  const first = last - (weeks - 1) * WEEK;
  const rows: TrendWeek[] = Array.from({ length: weeks }, (_, i) => ({ weekStart: new Date(first + i * WEEK).toISOString().slice(0, 10), opened: 0, closed: 0 }));
  const slot = (iso: string | null | undefined): number | null => {
    if (!iso) return null;
    const t = Date.parse(iso);
    if (Number.isNaN(t) || t < first || t >= last + WEEK) return null;
    return Math.floor((weekStartOf(t) - first) / WEEK);
  };
  for (const f of findings) {
    const o = slot(f.createdAt);
    if (o !== null) rows[o].opened += 1;
    const c = slot(f.resolvedAt);
    if (c !== null) rows[c].closed += 1;
  }
  return rows;
}

/** "Over these weeks 12 were raised and 9 closed: 3 more open than at the start." (or fewer, or the same). */
export function trendSentence(rows: TrendWeek[]): string {
  const opened = rows.reduce((n, r) => n + r.opened, 0);
  const closed = rows.reduce((n, r) => n + r.closed, 0);
  const net = opened - closed;
  const tail = net === 0 ? 'the open count is where it started' : net > 0 ? `${net} more open than at the start` : `${-net} fewer open than at the start`;
  return `Over these ${rows.length} weeks ${opened} ${opened === 1 ? 'was' : 'were'} raised and ${closed} closed: ${tail}.`;
}
