import { describe, expect, it } from 'vitest';
import type { Case } from '@/lib/api';
import { caseTicketNote } from './ticketNote';

const base: Case = { id: 'c1', title: ' Mailbox forwarding rule ', status: 'resolved', severity: 'high', createdAt: '2026-11-10T14:00:00Z', updatedAt: '2026-11-10T16:00:00Z' };

describe('caseTicketNote', () => {
  it('writes a full case as plain lines with times in UTC', () => {
    const note = caseTicketNote({
      ...base,
      caseNumber: 'INC-042',
      clientName: 'Acme Dental',
      assignee: 'pat@liveoak.test',
      alertCount: 3,
      description: 'A rule forwarded all mail to an outside address.',
      resolution: 'Rule removed, sessions revoked, password reset.',
      resolvedAt: '2026-11-10T15:30:00Z',
      timeline: [
        { id: 'b', type: 'note', timestamp: '2026-11-10T15:00:00Z', title: 'Sessions revoked', actor: 'pat' },
        { id: 'a', type: 'note', timestamp: '2026-11-10T14:05:00Z', title: 'Case opened' },
      ],
    });
    expect(note).toBe(
      [
        'A.C.O.R.N case INC-042: Mailbox forwarding rule',
        'Client: Acme Dental',
        'Severity: high. Status: Resolved.',
        'Opened: 2026-11-10 14:00 UTC. Resolved: 2026-11-10 15:30 UTC.',
        'Assigned to: pat@liveoak.test',
        'Alerts in this case: 3',
        '',
        'What happened:',
        'A rule forwarded all mail to an outside address.',
        '',
        'Resolution:',
        'Rule removed, sessions revoked, password reset.',
        '',
        'Timeline:',
        '- 2026-11-10 14:05 UTC: Case opened',
        '- 2026-11-10 15:00 UTC: Sessions revoked (pat)',
      ].join('\n'),
    );
  });

  it('leaves out what the case does not have, rather than showing it empty', () => {
    expect(caseTicketNote({ ...base, status: 'open', description: '   ' })).toBe(['A.C.O.R.N case: Mailbox forwarding rule', 'Severity: high. Status: Open.', 'Opened: 2026-11-10 14:00 UTC.'].join('\n'));
  });

  it('counts alerts from the list when there is no stored count, and shows zero as zero', () => {
    expect(caseTicketNote({ ...base, alertIds: ['a', 'b'] })).toContain('Alerts in this case: 2');
    expect(caseTicketNote({ ...base, alertCount: 0 })).toContain('Alerts in this case: 0');
  });

  it('keeps only the last eight events of a long timeline and says so; an event with a bad time is dropped', () => {
    const timeline = Array.from({ length: 10 }, (_, i) => ({ id: String(i), type: 'note', timestamp: `2026-11-10T14:${String(i).padStart(2, '0')}:00Z`, title: `Step ${i}` }));
    const note = caseTicketNote({ ...base, timeline: [...timeline, { id: 'x', type: 'note', timestamp: 'not a date', title: 'Broken' }] });
    expect(note).toContain('Timeline (last 8 of 10):');
    expect(note).not.toContain('Step 1\n');
    expect(note).toContain('Step 2');
    expect(note).toContain('Step 9');
    expect(note).not.toContain('Broken');
  });
});
