import { describe, expect, it } from 'vitest';
import { EXPLOITED_FIX_DAYS, exploitDue, exploitDueText, overTargetCount, targetStanding } from './vulnTarget';

const NOW = Date.parse('2026-11-11T12:00:00Z');
const ago = (hours: number) => new Date(NOW - hours * 3_600_000).toISOString();

describe('targetStanding', () => {
  it('is over only once the finding has been open longer than its severity allows', () => {
    expect(targetStanding('critical', ago(3), NOW)).toEqual({ hours: 4, over: false });
    expect(targetStanding('critical', ago(4), NOW)).toEqual({ hours: 4, over: false });
    expect(targetStanding('critical', ago(5), NOW)).toEqual({ hours: 4, over: true });
    expect(targetStanding('high', ago(25), NOW)).toEqual({ hours: 24, over: true });
    expect(targetStanding('medium', ago(119), NOW)).toEqual({ hours: 120, over: false });
    expect(targetStanding('low', ago(14 * 24 + 1), NOW)).toEqual({ hours: 336, over: true });
  });

  it('has no clock for info, an unknown severity, a missing date or a date that cannot be read', () => {
    expect(targetStanding('info', ago(999), NOW)).toBeNull();
    expect(targetStanding('weird', ago(999), NOW)).toBeNull();
    expect(targetStanding('high', null, NOW)).toBeNull();
    expect(targetStanding('high', undefined, NOW)).toBeNull();
    expect(targetStanding('high', 'not a date', NOW)).toBeNull();
  });
});

describe('overTargetCount', () => {
  it('counts the findings past their target and ignores the ones with no clock', () => {
    const findings = [
      { severity: 'critical', createdAt: ago(10) },
      { severity: 'high', createdAt: ago(2) },
      { severity: 'info', createdAt: ago(999) },
      { severity: 'low', createdAt: null },
    ];
    expect(overTargetCount(findings, NOW)).toBe(1);
    expect(overTargetCount([], NOW)).toBe(0);
  });
});

describe('exploitDue', () => {
  it('gives a known-exploited vulnerability two weeks from the day it was first seen, counted in whole days', () => {
    expect(EXPLOITED_FIX_DAYS).toBe(14);
    expect(exploitDue('2026-11-06T23:50:00Z', NOW)).toEqual({ date: '2026-11-20', days: 9, over: false });
    expect(exploitDue('2026-10-28T00:10:00Z', NOW)).toEqual({ date: '2026-11-11', days: 0, over: false });
    expect(exploitDue('2026-10-27T08:00:00Z', NOW)).toEqual({ date: '2026-11-10', days: 1, over: true });
    expect(exploitDue('2026-09-01T08:00:00Z', NOW)).toEqual({ date: '2026-09-15', days: 57, over: true });
  });

  it('has no due date for a date that cannot be read', () => {
    expect([exploitDue('', NOW), exploitDue(null, NOW), exploitDue('soon', NOW)]).toEqual([null, null, null]);
  });

  it('says it in words', () => {
    expect(exploitDueText({ date: '2026-11-20', days: 9, over: false })).toBe('fix by 2026-11-20 (9 days left)');
    expect(exploitDueText({ date: '2026-11-12', days: 1, over: false })).toBe('fix by 2026-11-12 (1 day left)');
    expect(exploitDueText({ date: '2026-11-11', days: 0, over: false })).toBe('fix by 2026-11-11 (today)');
    expect(exploitDueText({ date: '2026-11-10', days: 1, over: true })).toBe('fix was due 2026-11-10 (1 day ago)');
  });
});
