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
