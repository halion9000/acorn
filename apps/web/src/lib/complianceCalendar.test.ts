import { describe, expect, it } from 'vitest';
import type { AccessReviewRow, AuditRow } from '@/lib/api';
import { buildCalendar, groupByMonth } from '@/lib/complianceCalendar';

const review = (over: Partial<AccessReviewRow>): AccessReviewRow => ({ id: 'r', name: 'Q4 review', system: 'Microsoft 365', reviewer: 'Ann', due_date: '2026-12-01', status: 'open', overdue: false, summary: '', people: 0, pending: 0, keep: 0, remove: 0, flagged: 0, created_at: '', completed_at: null, completed_by: null, ...over });
const audit = (over: Partial<AuditRow>): AuditRow => ({ id: 'a', name: 'SOC 2 Type II', framework: 'SOC2', auditor: 'Firm LLP', period_start: null, period_end: '2027-01-31', status: 'fieldwork', requests: 0, open: 0, provided: 0, accepted: 0, overdue: 0, created_at: '', ...over });
const today = '2026-11-16';

describe('the compliance calendar', () => {
  it('merges the three sources soonest first, names where each is handled, and marks what is past due', () => {
    const cal = buildCalendar({
      governance: [{ id: 'g1', kind: 'policy', title: 'Acceptable use', owner: 'Hal', next_due: '2026-12-20' }, { id: 'g2', kind: 'vendor', title: 'Vendor review: Pax8', owner: '', next_due: '2026-11-05' }],
      reviews: [review({})],
      audits: [audit({})],
    }, today);
    expect(cal.map((e) => [e.date, e.kind, e.overdue])).toEqual([
      ['2026-11-05', 'Vendor review', true],
      ['2026-12-01', 'Access review', false],
      ['2026-12-20', 'Policy review', false],
      ['2027-01-31', 'Audit period ends', false],
    ]);
    expect(cal.find((e) => e.kind === 'Vendor review')!.link).toBe('/compliance/vendors');
    expect(cal.find((e) => e.kind === 'Access review')!.title).toBe('Q4 review (Microsoft 365)');
  });

  it('leaves out finished reviews and audits, and anything with no usable date', () => {
    const cal = buildCalendar({
      governance: [{ id: 'g', kind: 'other', title: 'No date', owner: '', next_due: '' }, { id: 'h', kind: 'other', title: 'Bad date', owner: '', next_due: '2026-13-45' }],
      reviews: [review({ status: 'complete' }), review({ due_date: null })],
      audits: [audit({ status: 'complete' }), audit({ period_end: null })],
    }, today);
    expect(cal).toEqual([]);
    expect(buildCalendar({}, today)).toEqual([]);
  });

  it('groups upcoming entries by month with overdue ones first in their own group, today itself not overdue', () => {
    const cal = buildCalendar({ governance: [
      { id: '1', kind: 'policy', title: 'A', owner: '', next_due: '2026-10-01' },
      { id: '2', kind: 'policy', title: 'B', owner: '', next_due: '2026-11-16' },
      { id: '3', kind: 'policy', title: 'C', owner: '', next_due: '2026-12-05' },
      { id: '4', kind: 'policy', title: 'D', owner: '', next_due: '2026-12-31' },
    ] }, today);
    expect(groupByMonth(cal).map((g) => [g.label, g.entries.map((e) => e.title)])).toEqual([['Overdue', ['A']], ['2026-11', ['B']], ['2026-12', ['C', 'D']]]);
  });
});
