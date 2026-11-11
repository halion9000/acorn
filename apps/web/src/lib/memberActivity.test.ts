import { describe, expect, it } from 'vitest';
import { quietAccountNote } from './memberActivity';

const NOW = Date.parse('2026-11-11T12:00:00Z');
const ago = (days: number) => new Date(NOW - days * 86_400_000).toISOString();
const m = (over: Partial<{ is_active: boolean; last_login: string | null; created_at: string }>) => ({ is_active: true, last_login: ago(1), created_at: ago(400), ...over });

describe('quietAccountNote', () => {
  it('says how long an active account has gone without a sign-in once it is past 90 days', () => {
    expect(quietAccountNote(m({ last_login: ago(120) }), NOW)).toBe('No sign-in for 120 days');
    expect(quietAccountNote(m({ last_login: ago(91) }), NOW)).toBe('No sign-in for 91 days');
    expect(quietAccountNote(m({ last_login: ago(90) }), NOW)).toBeNull();
    expect(quietAccountNote(m({ last_login: ago(2) }), NOW)).toBeNull();
  });

  it('says an old account never signed in, but not a new one', () => {
    expect(quietAccountNote(m({ last_login: null, created_at: ago(200) }), NOW)).toBe('Never signed in');
    expect(quietAccountNote(m({ last_login: null, created_at: ago(10) }), NOW)).toBeNull();
  });

  it('says nothing for an account that is switched off or whose dates cannot be read', () => {
    expect(quietAccountNote(m({ is_active: false, last_login: ago(500) }), NOW)).toBeNull();
    expect(quietAccountNote(m({ last_login: 'nope' }), NOW)).toBeNull();
    expect(quietAccountNote(m({ last_login: null, created_at: 'nope' }), NOW)).toBeNull();
  });
});

describe('byQuietest', () => {
  it('puts never-signed-in first, then the oldest sign-in, keeps ties in order and does not change the input', async () => {
    const { byQuietest } = await import('./memberActivity');
    const input = [
      { id: 'recent', last_login: ago(1) },
      { id: 'never-a', last_login: null },
      { id: 'old', last_login: ago(300) },
      { id: 'never-b', last_login: null },
      { id: 'bad', last_login: 'nope' },
    ];
    expect(byQuietest(input).map((m) => m.id)).toEqual(['never-a', 'never-b', 'bad', 'old', 'recent']);
    expect(input.map((m) => m.id)).toEqual(['recent', 'never-a', 'old', 'never-b', 'bad']);
    expect(byQuietest([])).toEqual([]);
  });
});
