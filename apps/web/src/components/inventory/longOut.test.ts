import { describe, expect, it } from 'vitest';
import { longOutCount, longOutNote } from './longOut';

const NOW = Date.parse('2026-11-11T12:00:00Z');
const ago = (d: number) => new Date(NOW - d * 86_400_000).toISOString();

describe('longOutNote', () => {
  it('says how long an item has been out once it is past 30 days', () => {
    expect(longOutNote({ status: 'checked_out', checked_out_at: ago(45) }, NOW)).toBe('Out 45 days');
    expect(longOutNote({ status: 'checked_out', checked_out_at: ago(31) }, NOW)).toBe('Out 31 days');
    expect(longOutNote({ status: 'checked_out', checked_out_at: ago(30) }, NOW)).toBeNull();
  });
  it('says nothing for an item that is in, retired, or has no readable date', () => {
    expect(longOutNote({ status: 'checked_in', checked_out_at: ago(90) }, NOW)).toBeNull();
    expect(longOutNote({ status: 'retired', checked_out_at: ago(90) }, NOW)).toBeNull();
    expect(longOutNote({ status: 'checked_out', checked_out_at: null }, NOW)).toBeNull();
    expect(longOutNote({ status: 'checked_out', checked_out_at: 'nope' }, NOW)).toBeNull();
  });
  it('counts them', () => {
    expect(longOutCount([{ status: 'checked_out', checked_out_at: ago(45) }, { status: 'checked_out', checked_out_at: ago(2) }, { status: 'checked_in', checked_out_at: ago(99) }], NOW)).toBe(1);
  });
});
