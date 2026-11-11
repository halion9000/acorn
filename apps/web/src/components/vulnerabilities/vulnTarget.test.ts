import { describe, expect, it } from 'vitest';
import { overTargetCount, targetStanding } from './vulnTarget';

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
