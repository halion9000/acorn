import { describe, expect, it } from 'vitest';
import { clamp, formatPct, thresholdsEqual, validate } from './AutonomyPolicy';

const triple = (auto: number, review: number, escalation: number) => ({ auto, review, escalation });

describe('validate', () => {
  it('accepts three thresholds in order, including the edges', () => {
    expect(validate(triple(0.9, 0.6, 0.3))).toEqual({ ok: true });
    expect(validate(triple(1, 1, 1))).toEqual({ ok: true });
    expect(validate(triple(0, 0, 0))).toEqual({ ok: true });
    expect(validate(triple(0.8, 0.8, 0.8))).toEqual({ ok: true });
  });

  it('refuses a value outside 0 to 1, naming which one', () => {
    expect(validate(triple(1.01, 0.5, 0.2))).toEqual({ ok: false, reason: 'auto must be between 0 and 1' });
    expect(validate(triple(0.9, -0.1, -0.2))).toEqual({ ok: false, reason: 'review must be between 0 and 1' });
    expect(validate(triple(0.9, 0.5, 2))).toEqual({ ok: false, reason: 'escalation must be between 0 and 1' });
  });

  it('refuses NaN and infinity: an empty or half-typed field must not be saved', () => {
    expect(validate(triple(Number.NaN, 0.5, 0.2))).toEqual({ ok: false, reason: 'auto must be between 0 and 1' });
    expect(validate(triple(0.9, Number.NaN, 0.2))).toEqual({ ok: false, reason: 'review must be between 0 and 1' });
    expect(validate(triple(0.9, 0.5, Number.NaN))).toEqual({ ok: false, reason: 'escalation must be between 0 and 1' });
    expect(validate(triple(Number.POSITIVE_INFINITY, 0.5, 0.2)).ok).toBe(false);
    expect(validate(triple(0.9, 0.5, Number.NEGATIVE_INFINITY)).ok).toBe(false);
  });

  it('refuses thresholds out of order', () => {
    expect(validate(triple(0.5, 0.6, 0.1))).toEqual({ ok: false, reason: 'review must be ≤ auto' });
    expect(validate(triple(0.9, 0.4, 0.5))).toEqual({ ok: false, reason: 'escalation must be ≤ review' });
  });
});

describe('clamp, formatPct and thresholdsEqual', () => {
  it('clamp keeps a number within its range and turns NaN into the low end', () => {
    expect(clamp(0.5)).toBe(0.5);
    expect(clamp(-3)).toBe(0);
    expect(clamp(7)).toBe(1);
    expect(clamp(Number.NaN)).toBe(0);
    expect(clamp(50, 10, 20)).toBe(20);
    expect(clamp(Number.NaN, 10, 20)).toBe(10);
  });

  it('formatPct shows whole percent', () => {
    expect(formatPct(0.855)).toBe('86%');
    expect(formatPct(0)).toBe('0%');
    expect(formatPct(1)).toBe('100%');
  });

  it('two triples are equal when each threshold is, to a rounding error, and not otherwise', () => {
    expect(thresholdsEqual(triple(0.9, 0.6, 0.3), triple(0.9, 0.6, 0.3))).toBe(true);
    expect(thresholdsEqual(triple(0.1 + 0.2, 0.6, 0.3), triple(0.3, 0.6, 0.3))).toBe(true);
    expect(thresholdsEqual(triple(0.9, 0.6, 0.3), triple(0.9, 0.61, 0.3))).toBe(false);
    expect(thresholdsEqual(triple(0.9, 0.6, 0.3), triple(0.9, 0.6, 0.31))).toBe(false);
  });
});
