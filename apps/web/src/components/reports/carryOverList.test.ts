import { describe, expect, it } from 'vitest';

import { CARRY_LIST_CAP, ageLabel, byUrgency, carryOverText } from './carryOverList';

const now = Date.parse('2026-11-11T12:00:00Z');

describe('ageLabel', () => {
  it('says minutes, hours or days, and a dash for no date, a bad date or a future one', () => {
    expect(ageLabel('2026-11-11T11:20:00Z', now)).toBe('40 min');
    expect(ageLabel('2026-11-11T07:00:00Z', now)).toBe('5 h');
    expect(ageLabel('2026-11-08T11:00:00Z', now)).toBe('3 d');
    expect(ageLabel(undefined, now)).toBe('–');
    expect(ageLabel('nonsense', now)).toBe('–');
    expect(ageLabel('2026-11-12T00:00:00Z', now)).toBe('–');
  });
});

describe('byUrgency', () => {
  it('puts the most severe first, then the one that has waited longest, and leaves the input alone', () => {
    const input = [
      { id: 'h-new', severity: 'high', createdAt: '2026-11-11T10:00:00Z' },
      { id: 'c-new', severity: 'critical', createdAt: '2026-11-11T11:00:00Z' },
      { id: 'h-old', severity: 'high', createdAt: '2026-11-01T10:00:00Z' },
      { id: 'c-old', severity: 'critical', createdAt: '2026-11-10T11:00:00Z' },
      { id: 'h-nodate', severity: 'high' },
    ];
    expect(byUrgency(input).map((x) => x.id)).toEqual(['c-old', 'c-new', 'h-old', 'h-new', 'h-nodate']);
    expect(input[0].id).toBe('h-new');
  });
});

describe('carryOverText', () => {
  it('lists each alert and case with its client, age and owner, most urgent first', () => {
    const text = carryOverText(
      {
        alertTotal: 2,
        alerts: [
          { id: 'a2', title: 'Odd sign-in', severity: 'high', createdAt: '2026-11-11T07:00:00Z', assignee: 'sam@example.com' },
          { id: 'a1', title: 'Ransomware canary', severity: 'critical', clientName: 'Acme', createdAt: '2026-11-11T11:20:00Z' },
        ],
        cases: [{ id: 'c1', caseNumber: 'INC-007', title: 'Mailbox takeover', severity: 'high', status: 'in_progress', clientName: 'Acme', createdAt: '2026-11-08T11:00:00Z' }],
      },
      now,
    );
    expect(text.split('\n')).toEqual([
      'Carry over, 2026-11-11 12:00 UTC',
      '',
      'Critical and high alerts still open: 2',
      '- [critical] Ransomware canary (Acme), open 40 min, with nobody',
      '- [high] Odd sign-in, open 5 h, with sam@example.com',
      '',
      'Cases still open: 1',
      '- [high] INC-007 Mailbox takeover (Acme), in progress, open 3 d, with nobody',
    ]);
  });

  it('counts what the cap leaves out instead of listing it, and says zero when nothing is open', () => {
    const many = Array.from({ length: CARRY_LIST_CAP + 3 }, (_, i) => ({ id: `a${i}`, title: `Alert ${i}`, severity: 'high', createdAt: '2026-11-11T07:00:00Z' }));
    const text = carryOverText({ alertTotal: 90, alerts: many, cases: [] }, now);
    expect(text.match(/^- \[high\]/gm)).toHaveLength(CARRY_LIST_CAP);
    expect(text).toContain(`- and ${90 - CARRY_LIST_CAP} more`);
    expect(text).toContain('Cases still open: 0');
  });
});
