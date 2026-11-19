import { describe, expect, it } from 'vitest';
import { NA, deltaTone, formatCompact, formatDelta, formatDuration, formatMoney, formatNumber, formatPercent, formatRelative, marginTone } from './format';

describe('formatNumber', () => {
  it('uses separators, a real minus sign and n/a for a missing value', () => {
    expect([formatNumber(12345.6), formatNumber(1234.5, 1), formatNumber(-42), formatNumber(0), formatNumber(null), formatNumber(NaN)]).toEqual(['12,346', '1,234.5', '−42', '0', NA, NA]);
  });
  it('does not show a minus for a negative that rounds to zero', () => {
    expect(formatNumber(-0.2)).toBe('0');
  });
});

describe('formatCompact', () => {
  it('shortens thousands, millions and billions', () => {
    expect([formatCompact(950), formatCompact(12500), formatCompact(1_250_000), formatCompact(3_000_000_000), formatCompact(-20000), formatCompact(undefined)]).toEqual(['950', '12.5K', '1.3M', '3B', '−20K', NA]);
  });
});

describe('formatMoney', () => {
  it('writes dollars, cents on request, and a minus before the dollar sign', () => {
    expect([formatMoney(1234.5), formatMoney(1234.5, true), formatMoney(-980), formatMoney(-0.2), formatMoney(null)]).toEqual(['$1,235', '$1,234.50', '−$980', '$0', NA]);
  });
});

describe('formatPercent and formatDelta', () => {
  it('writes percents, and a change with its sign', () => {
    expect([formatPercent(12.345), formatPercent(null), formatDelta(12.34), formatDelta(-5), formatDelta(0), formatDelta(0.01), formatDelta(null)]).toEqual(['12.3%', NA, '+12.3%', '−5.0%', '0.0%', '0.0%', NA]);
  });
});

describe('formatDuration', () => {
  it('uses the two biggest units', () => {
    expect([formatDuration(45), formatDuration(90), formatDuration(120), formatDuration(1500), formatDuration(2880), formatDuration(null)]).toEqual(['45 min', '1 h 30 min', '2 h', '1 d 1 h', '2 d', NA]);
  });
});

describe('formatRelative', () => {
  const now = Date.parse('2026-11-18T12:00:00Z');
  it('says how long ago, then the date', () => {
    expect([
      formatRelative('2026-11-18T11:59:30Z', now),
      formatRelative('2026-11-18T11:57:00Z', now),
      formatRelative('2026-11-18T09:00:00Z', now),
      formatRelative('2026-11-17T09:00:00Z', now),
      formatRelative('2026-11-10T09:00:00Z', now),
      formatRelative('2026-08-01T09:00:00Z', now),
      formatRelative('nope', now),
      formatRelative(null, now),
    ]).toEqual(['just now', '3 minutes ago', '3 hours ago', 'yesterday', '8 days ago', '2026-08-01', NA, NA]);
  });
});

describe('tones', () => {
  it('reads a change as good or bad depending on which way is good, and a margin against its bands', () => {
    expect([deltaTone(5), deltaTone(-5), deltaTone(-5, false), deltaTone(5, false), deltaTone(0), deltaTone(null)]).toEqual(['good', 'bad', 'good', 'bad', 'neutral', 'neutral']);
    expect([marginTone(55), marginTone(30), marginTone(10), marginTone(null), marginTone(40), marginTone(19.9)]).toEqual(['good', 'neutral', 'bad', 'neutral', 'good', 'bad']);
  });
});
