/**
 * The framework gap report: for each framework, the controls that have NO accepted evidence and NO named owner, which nobody is working on and nothing proves. Pure over the control list the
 * Controls page already holds. A control with only one of the two is counted separately so the report can say what is missing without hiding a half-done control.
 */
import type { ControlRowT } from '@/lib/api';

export interface FrameworkGaps {
  framework: string;
  total: number;
  noEvidence: number;
  noOwner: number;
  /** Controls with neither accepted evidence nor an owner. */
  bothMissing: ControlRowT[];
}

const hasOwner = (r: ControlRowT): boolean => typeof r.owner === 'string' && r.owner.trim() !== '';

/** One entry per framework in the list, the one with most controls missing both first, then by name (pure). */
export function gapReport(rows: ControlRowT[]): FrameworkGaps[] {
  const by = new Map<string, FrameworkGaps>();
  for (const r of rows) {
    const g = by.get(r.framework) ?? { framework: r.framework, total: 0, noEvidence: 0, noOwner: 0, bothMissing: [] };
    g.total += 1;
    const noEvidence = r.accepted === 0;
    const noOwner = !hasOwner(r);
    if (noEvidence) g.noEvidence += 1;
    if (noOwner) g.noOwner += 1;
    if (noEvidence && noOwner) g.bothMissing.push(r);
    by.set(r.framework, g);
  }
  return [...by.values()].sort((a, b) => b.bothMissing.length - a.bothMissing.length || a.framework.localeCompare(b.framework));
}

const q = (v: string): string => {
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

/** The controls missing both, as a CSV (framework, control, title, group, health). */
export function gapCsv(report: FrameworkGaps[]): string {
  const lines = ['framework,control,title,group,health'];
  for (const g of report) for (const r of g.bothMissing) lines.push([r.framework, r.control_id, r.title, r.group, r.state].map(q).join(','));
  return lines.join('\r\n') + '\r\n';
}
