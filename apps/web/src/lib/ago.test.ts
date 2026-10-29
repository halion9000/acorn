import { describe, expect, it } from 'vitest';
import { ago, agoMinutes, daysAgo, toMillis } from './ago';

const NOW = Date.parse('2026-10-29T12:00:00Z');
const before = (ms: number) => new Date(NOW - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

describe('ago, long style', () => {
  it('counts in whole units and changes unit at two minutes, two hours and two days', () => {
    expect(ago(before(30_000), { now: NOW })).toBe('just now');
    expect(ago(before(119_000), { now: NOW })).toBe('just now');
    expect(ago(before(2 * MIN), { now: NOW })).toBe('2 minutes ago');
    expect(ago(before(119 * MIN), { now: NOW })).toBe('119 minutes ago');
    expect(ago(before(2 * HOUR), { now: NOW })).toBe('2 hours ago');
    expect(ago(before(47 * HOUR + 59 * MIN), { now: NOW })).toBe('47 hours ago');
    expect(ago(before(2 * DAY), { now: NOW })).toBe('2 days ago');
    expect(ago(before(400 * DAY), { now: NOW })).toBe('400 days ago');
  });

  it('cuts down, never rounds up: 59 minutes is not an hour', () => {
    expect(ago(before(59 * MIN + 59_000), { now: NOW })).toBe('59 minutes ago');
    expect(ago(before(23 * HOUR + 59 * MIN), { now: NOW })).toBe('23 hours ago');
  });
});

describe('ago, short style', () => {
  it('says just now for the first minute, then minutes, hours up to two days, then days', () => {
    expect(ago(before(59_000), { now: NOW, style: 'short' })).toBe('just now');
    expect(ago(before(MIN), { now: NOW, style: 'short' })).toBe('1m ago');
    expect(ago(before(59 * MIN), { now: NOW, style: 'short' })).toBe('59m ago');
    expect(ago(before(47 * HOUR), { now: NOW, style: 'short' })).toBe('47h ago');
    expect(ago(before(3 * DAY), { now: NOW, style: 'short' })).toBe('3d ago');
  });

  it('can count seconds, and can give the date itself after some days', () => {
    expect(ago(before(12_000), { now: NOW, style: 'short', seconds: true })).toBe('12s ago');
    expect(ago(before(300), { now: NOW, style: 'short', seconds: true })).toBe('just now');
    expect(ago(before(12_000), { now: NOW, seconds: true })).toBe('12 seconds ago');
    expect(ago(before(1_000), { now: NOW, seconds: true })).toBe('1 second ago');
    const old = before(40 * DAY);
    expect(ago(old, { now: NOW, style: 'short', dateAfterDays: 30 })).toBe(new Date(old).toLocaleDateString());
    expect(ago(before(29 * DAY), { now: NOW, style: 'short', dateAfterDays: 30 })).toBe('29d ago');
  });
});

describe('a time that cannot be read, or is in the future', () => {
  it('says what the caller chose and never NaN', () => {
    for (const bad of [null, undefined, '', 'yesterday-ish', 'NaN', NaN]) {
      expect(ago(bad, { now: NOW })).toBe('never');
      expect(ago(bad, { now: NOW, missing: '—' })).toBe('—');
    }
    expect(ago('2026-13-45T00:00:00Z', { now: NOW, missing: '' })).toBe('');
  });

  it('a time ahead of the clock is just now, not a negative number', () => {
    expect(ago(new Date(NOW + 5 * DAY), { now: NOW })).toBe('just now');
    expect(ago(NOW + 90_000, { now: NOW, style: 'short' })).toBe('just now');
  });

  it('takes a number or a Date as well as a string', () => {
    expect(ago(NOW - 3 * HOUR, { now: NOW })).toBe('3 hours ago');
    expect(ago(new Date(NOW - 3 * HOUR), { now: NOW })).toBe('3 hours ago');
    expect(toMillis(new Date('nope'))).toBeNull();
  });
});

describe('daysAgo', () => {
  it('says today, 1 day ago, or N days ago', () => {
    expect(daysAgo(before(HOUR), { now: NOW })).toBe('today');
    expect(daysAgo(before(DAY + HOUR), { now: NOW })).toBe('1 day ago');
    expect(daysAgo(before(12 * DAY), { now: NOW })).toBe('12 days ago');
    expect(daysAgo(new Date(NOW + DAY), { now: NOW })).toBe('today');
  });

  it('an invalid date is said so, not "NaN days ago"', () => {
    expect(daysAgo('not a date', { now: NOW })).toBe('unknown date');
    expect(daysAgo(null, { now: NOW, missing: '' })).toBe('');
  });
});

describe('the just-now window and ages given in minutes', () => {
  it('can be widened or narrowed, and counting seconds starts after it', () => {
    expect(ago(before(4_000), { now: NOW, style: 'short', seconds: true, justNowSeconds: 5 })).toBe('just now');
    expect(ago(before(6_000), { now: NOW, style: 'short', seconds: true, justNowSeconds: 5 })).toBe('6s ago');
    expect(ago(before(90_000), { now: NOW, style: 'short', justNowSeconds: 30 })).toBe('1m ago');
    expect(ago(before(45_000), { now: NOW, style: 'short', justNowSeconds: 30 })).toBe('just now');
    expect(ago(before(150_000), { now: NOW, justNowSeconds: 300 })).toBe('just now');
  });

  it('agoMinutes reads an age in minutes the same way', () => {
    expect(agoMinutes(0, { now: NOW })).toBe('just now');
    expect(agoMinutes(90, { now: NOW })).toBe('90 minutes ago');
    expect(agoMinutes(60 * 30, { now: NOW })).toBe('30 hours ago');
    expect(agoMinutes(60 * 24 * 5, { now: NOW })).toBe('5 days ago');
    for (const bad of [null, undefined, NaN]) expect(agoMinutes(bad, { now: NOW })).toBe('never');
    expect(agoMinutes(null, { now: NOW, missing: '—' })).toBe('—');
  });
});
