import { describe, expect, it } from 'vitest';
import { trendSentence, weekStartOf, weeklyTrend } from './vulnTrend';

// Wednesday 2026-11-11 12:00 UTC: its week starts Monday 2026-11-09.
const NOW = Date.parse('2026-11-11T12:00:00Z');

describe('weekStartOf', () => {
  it('is the Monday at midnight UTC, for any day of the week', () => {
    expect(new Date(weekStartOf(NOW)).toISOString()).toBe('2026-11-09T00:00:00.000Z');
    expect(new Date(weekStartOf(Date.parse('2026-11-15T23:59:59Z'))).toISOString()).toBe('2026-11-09T00:00:00.000Z'); // Sunday
    expect(new Date(weekStartOf(Date.parse('2026-11-09T00:00:00Z'))).toISOString()).toBe('2026-11-09T00:00:00.000Z'); // Monday itself
  });
});

describe('weeklyTrend', () => {
  it('lists every week oldest first with no gaps, counting raised and closed in their own weeks', () => {
    const rows = weeklyTrend(
      [
        { createdAt: '2026-11-10T08:00:00Z', resolvedAt: null }, // raised this week
        { createdAt: '2026-11-03T08:00:00Z', resolvedAt: '2026-11-10T09:00:00Z' }, // raised last week, closed this week
        { createdAt: '2026-10-27T08:00:00Z', resolvedAt: '2026-10-28T08:00:00Z' }, // raised and closed two weeks ago
        { createdAt: '2026-01-01T08:00:00Z', resolvedAt: '2026-11-04T08:00:00Z' }, // raised long ago (not counted), closed last week
      ],
      NOW,
      3,
    );
    expect(rows).toEqual([
      { weekStart: '2026-10-26', opened: 1, closed: 1 },
      { weekStart: '2026-11-02', opened: 1, closed: 1 },
      { weekStart: '2026-11-09', opened: 1, closed: 1 },
    ]);
  });

  it('ignores dates that cannot be read or are in the future beyond this week, and gives empty weeks for nothing', () => {
    const rows = weeklyTrend([{ createdAt: 'nope', resolvedAt: undefined }, { createdAt: '2027-01-01T00:00:00Z' }], NOW, 2);
    expect(rows).toEqual([
      { weekStart: '2026-11-02', opened: 0, closed: 0 },
      { weekStart: '2026-11-09', opened: 0, closed: 0 },
    ]);
    expect(weeklyTrend([], NOW)).toHaveLength(8);
  });
});

describe('trendSentence', () => {
  const w = (opened: number, closed: number) => ({ weekStart: 'x', opened, closed });
  it('says whether more or fewer are open than at the start', () => {
    expect(trendSentence([w(8, 3), w(4, 6)])).toBe('Over these 2 weeks 12 were raised and 9 closed: 3 more open than at the start.');
    expect(trendSentence([w(1, 4)])).toBe('Over these 1 weeks 1 was raised and 4 closed: 3 fewer open than at the start.');
    expect(trendSentence([w(2, 2)])).toBe('Over these 1 weeks 2 were raised and 2 closed: the open count is where it started.');
  });
});
