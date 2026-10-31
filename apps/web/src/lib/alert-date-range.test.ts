import { describe, expect, it } from 'vitest';
import { dateRangeError, isDateLimited, parseDay, rangeToInstants } from './alert-date-range';

// A fixed "now" in the middle of a day, built in local time so the tests hold in any time zone.
const NOW = new Date(2026, 9, 14, 15, 30, 0); // 14 October 2026, 15:30 local
const local = (y: number, mo: number, d: number) => new Date(y, mo - 1, d).toISOString();

describe('rangeToInstants', () => {
  it('all time (and no choice at all) sends nothing', () => {
    expect(rangeToInstants(undefined, NOW)).toEqual({});
    expect(rangeToInstants({ preset: 'all' }, NOW)).toEqual({});
  });

  it('today is this local day, midnight to midnight', () => {
    expect(rangeToInstants({ preset: 'today' }, NOW)).toEqual({ since: local(2026, 10, 14), until: local(2026, 10, 15) });
  });

  it('yesterday is the whole day before, and does not include today', () => {
    expect(rangeToInstants({ preset: 'yesterday' }, NOW)).toEqual({ since: local(2026, 10, 13), until: local(2026, 10, 14) });
  });

  it('last 7 and last 30 days are whole days counted back from today, today included, with no end', () => {
    expect(rangeToInstants({ preset: '7d' }, NOW)).toEqual({ since: local(2026, 10, 8) });
    expect(rangeToInstants({ preset: '30d' }, NOW)).toEqual({ since: local(2026, 9, 15) });
  });

  it('counts back across a month and a year end', () => {
    expect(rangeToInstants({ preset: '7d' }, new Date(2027, 0, 3, 9, 0))).toEqual({ since: local(2026, 12, 28) });
    expect(rangeToInstants({ preset: 'yesterday' }, new Date(2026, 2, 1, 0, 5))).toEqual({ since: local(2026, 2, 28), until: local(2026, 3, 1) });
  });

  it('a custom range includes both its days: it ends at the start of the day after the last one', () => {
    expect(rangeToInstants({ preset: 'custom', from: '2026-10-01', to: '2026-10-03' }, NOW)).toEqual({ since: local(2026, 10, 1), until: local(2026, 10, 4) });
    expect(rangeToInstants({ preset: 'custom', from: '2026-10-05', to: '2026-10-05' }, NOW)).toEqual({ since: local(2026, 10, 5), until: local(2026, 10, 6) });
    expect(rangeToInstants({ preset: 'custom', to: '2026-12-31' }, NOW)).toEqual({ until: local(2027, 1, 1) });
  });

  it('a custom range may leave either end empty', () => {
    expect(rangeToInstants({ preset: 'custom', from: '2026-10-01' }, NOW)).toEqual({ since: local(2026, 10, 1) });
    expect(rangeToInstants({ preset: 'custom' }, NOW)).toEqual({});
  });

  it('a range that cannot be used sends nothing, so it never hides alerts', () => {
    expect(rangeToInstants({ preset: 'custom', from: '2026-10-05', to: '2026-10-01' }, NOW)).toEqual({});
    expect(rangeToInstants({ preset: 'custom', from: 'not a date' }, NOW)).toEqual({});
    expect(rangeToInstants({ preset: 'custom', from: '2026-02-30' }, NOW)).toEqual({});
  });
});

describe('dateRangeError', () => {
  it('names what is wrong with a custom range, and is quiet otherwise', () => {
    expect(dateRangeError(undefined)).toBeNull();
    expect(dateRangeError({ preset: '7d' })).toBeNull();
    expect(dateRangeError({ preset: 'custom', from: '2026-10-01', to: '2026-10-03' })).toBeNull();
    expect(dateRangeError({ preset: 'custom', from: '2026-10-05', to: '2026-10-01' })).toMatch(/start date is after the end date/);
    expect(dateRangeError({ preset: 'custom', from: '2026-13-01' })).toMatch(/start date is not a valid date/);
    expect(dateRangeError({ preset: 'custom', to: 'x' })).toMatch(/end date is not a valid date/);
  });
});

describe('parseDay and isDateLimited', () => {
  it('only real calendar days parse', () => {
    expect(parseDay('2026-10-14')?.getDate()).toBe(14);
    expect(parseDay('2026-02-29')).toBeNull();
    expect(parseDay('2026-1-4')).toBeNull();
    expect(parseDay(undefined)).toBeNull();
  });
  it('knows when the range actually limits the list', () => {
    expect(isDateLimited(undefined)).toBe(false);
    expect(isDateLimited({ preset: 'all' })).toBe(false);
    expect(isDateLimited({ preset: 'custom' })).toBe(false);
    expect(isDateLimited({ preset: 'today' })).toBe(true);
    expect(isDateLimited({ preset: 'custom', from: '2026-10-01' })).toBe(true);
  });
});
