import { describe, expect, it } from 'vitest';
import { evidenceAgeNote, newestAcceptedAgeDays, staleControlCount } from './evidenceAge';

const NOW = Date.parse('2026-11-11T12:00:00Z');
const daysAgo = (d: number, status = 'accepted') => ({ status, collected_at: new Date(NOW - d * 86_400_000).toISOString() });

describe('newestAcceptedAgeDays', () => {
  it('uses the newest accepted item only, whole days, never negative', () => {
    expect(newestAcceptedAgeDays([daysAgo(400), daysAgo(30), daysAgo(5, 'pending'), daysAgo(1, 'rejected')], NOW)).toBe(30);
    expect(newestAcceptedAgeDays([{ status: 'accepted', collected_at: new Date(NOW + 5 * 86_400_000).toISOString() }], NOW)).toBe(0);
  });
  it('is null when nothing is accepted or the dates cannot be read', () => {
    expect(newestAcceptedAgeDays([], NOW)).toBeNull();
    expect(newestAcceptedAgeDays([daysAgo(10, 'pending')], NOW)).toBeNull();
    expect(newestAcceptedAgeDays([{ status: 'accepted', collected_at: 'nope' }], NOW)).toBeNull();
  });
});

describe('evidenceAgeNote and staleControlCount', () => {
  it('says so only once the newest accepted evidence is more than a year old, in months', () => {
    expect(evidenceAgeNote([daysAgo(365)], NOW)).toBeNull();
    expect(evidenceAgeNote([daysAgo(366)], NOW)).toBe('The newest accepted evidence is 12 months old: refresh it.');
    expect(evidenceAgeNote([daysAgo(430)], NOW)).toBe('The newest accepted evidence is 14 months old: refresh it.');
    expect(evidenceAgeNote([daysAgo(700), daysAgo(20)], NOW)).toBeNull();
  });
  it('counts the controls that are stale', () => {
    expect(staleControlCount([[daysAgo(500)], [daysAgo(10)], [], [daysAgo(400), daysAgo(401)]], NOW)).toBe(2);
    expect(staleControlCount([], NOW)).toBe(0);
  });
});
