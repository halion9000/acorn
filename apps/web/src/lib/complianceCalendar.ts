/**
 * One calendar of everything that falls due in Compliance: policy and vendor reviews and other scheduled items (their next due date), open access reviews (their due date) and audits that are not
 * finished (the end of their period). Pure: it merges lists the pages already read. Soonest first; anything past today is marked overdue.
 */
import type { AccessReviewRow, AuditRow } from '@/lib/api';

export interface GovernanceDue {
  id: string;
  kind: 'policy' | 'vendor' | 'evidence' | 'other';
  title: string;
  owner: string;
  next_due: string;
}

export type CalendarKind = 'Policy review' | 'Vendor review' | 'Evidence' | 'Scheduled item' | 'Access review' | 'Audit period ends';

export interface CalendarEntry {
  /** YYYY-MM-DD. */
  date: string;
  kind: CalendarKind;
  title: string;
  owner: string;
  /** Where the thing is handled. */
  link: string;
  overdue: boolean;
}

const KIND: Record<GovernanceDue['kind'], { kind: CalendarKind; link: string }> = {
  policy: { kind: 'Policy review', link: '/compliance/policies' },
  vendor: { kind: 'Vendor review', link: '/compliance/vendors' },
  evidence: { kind: 'Evidence', link: '/compliance/controls' },
  other: { kind: 'Scheduled item', link: '/compliance/policies' },
};

const day = (v: string | null | undefined): string | null => {
  const d = (v ?? '').slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(d) && Number.isFinite(Date.parse(`${d}T00:00:00Z`)) ? d : null;
};

export function buildCalendar(input: { governance?: GovernanceDue[]; reviews?: AccessReviewRow[]; audits?: AuditRow[] }, today: string): CalendarEntry[] {
  const out: CalendarEntry[] = [];
  const add = (date: string | null, kind: CalendarKind, title: string, owner: string, link: string) => {
    if (date) out.push({ date, kind, title, owner, link, overdue: date < today });
  };
  for (const g of input.governance ?? []) add(day(g.next_due), KIND[g.kind].kind, g.title, g.owner ?? '', KIND[g.kind].link);
  for (const r of input.reviews ?? []) if (r.status === 'open') add(day(r.due_date), 'Access review', `${r.name} (${r.system})`, r.reviewer ?? '', '/compliance/access-reviews');
  for (const a of input.audits ?? []) if (a.status !== 'complete') add(day(a.period_end), 'Audit period ends', `${a.name} (${a.framework})`, a.auditor ?? '', '/compliance/audits');
  return out.sort((x, y) => (x.date === y.date ? x.title.localeCompare(y.title) : x.date < y.date ? -1 : 1));
}

/** The entries grouped by month (YYYY-MM), earliest month first; overdue entries are gathered in a group called "Overdue" that comes first (pure). */
export function groupByMonth(entries: CalendarEntry[]): { label: string; entries: CalendarEntry[] }[] {
  const groups: { label: string; entries: CalendarEntry[] }[] = [];
  const push = (label: string, e: CalendarEntry) => {
    const g = groups.find((x) => x.label === label);
    if (g) g.entries.push(e);
    else groups.push({ label, entries: [e] });
  };
  for (const e of entries.filter((x) => x.overdue)) push('Overdue', e);
  for (const e of entries.filter((x) => !x.overdue)) push(e.date.slice(0, 7), e);
  return groups;
}
