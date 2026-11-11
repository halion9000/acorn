import { describe, expect, it } from 'vitest';
import { statusLinkExpiryNote } from './statusLinkExpiry';

const NOW = Date.parse('2026-11-10T12:00:00Z');
const at = (days: number, extraHours = 0) => new Date(NOW + days * 86_400_000 + extraHours * 3_600_000).toISOString();

describe('statusLinkExpiryNote', () => {
  it('says so in the last week, counting whole days, and "today" within the last day', () => {
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(7) }, NOW)).toBe('Expires in 7 days');
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(3, 5) }, NOW)).toBe('Expires in 3 days');
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(1, 1) }, NOW)).toBe('Expires in 1 day');
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(0, 6) }, NOW)).toBe('Expires today');
  });

  it('says nothing for a link far from its end, one that has ended or been revoked, or a date that cannot be read', () => {
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(8) }, NOW)).toBeNull();
    expect(statusLinkExpiryNote({ state: 'live', expires_at: at(-1) }, NOW)).toBeNull();
    expect(statusLinkExpiryNote({ state: 'expired', expires_at: at(2) }, NOW)).toBeNull();
    expect(statusLinkExpiryNote({ state: 'revoked', expires_at: at(2) }, NOW)).toBeNull();
    expect(statusLinkExpiryNote({ state: 'live', expires_at: 'not a date' }, NOW)).toBeNull();
  });
});
