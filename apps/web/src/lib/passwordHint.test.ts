import { describe, expect, it } from 'vitest';
import { passwordHint } from './passwordHint';

describe('passwordHint', () => {
  it('says nothing for an empty box', () => {
    expect(passwordHint('')).toBeNull();
  });
  it('counts down to the minimum length', () => {
    expect(passwordHint('abc')).toEqual({ text: '9 more characters needed (at least 12).', ok: false });
    expect(passwordHint('a'.repeat(11))).toEqual({ text: '1 more character needed (at least 12).', ok: false });
  });
  it('refuses what the server refuses: too long, a space at either end, the same as the current one', () => {
    expect(passwordHint('a'.repeat(129))?.ok).toBe(false);
    expect(passwordHint(' twelve chars')?.text).toMatch(/space/);
    expect(passwordHint('twelve chars ')?.ok).toBe(false);
    expect(passwordHint('same password 1', 'same password 1')?.text).toMatch(/different/);
  });
  it('accepts twelve characters and says longer is stronger, and calls sixteen a good length', () => {
    expect(passwordHint('a'.repeat(12))).toEqual({ text: 'Long enough. Longer is stronger: three or four unrelated words work well.', ok: true });
    expect(passwordHint('correct horse battery')).toEqual({ text: 'Good length.', ok: true });
    expect(passwordHint('a'.repeat(128))?.ok).toBe(true);
  });
});
