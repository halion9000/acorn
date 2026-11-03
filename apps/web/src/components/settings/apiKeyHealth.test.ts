import { describe, expect, it } from 'vitest';
import { keyHealth } from './apiKeyHealth';

const NOW = Date.parse('2026-11-03T12:00:00Z');
const ago = (d: number) => new Date(NOW - d * 86_400_000).toISOString();
const ahead = (d: number) => new Date(NOW + d * 86_400_000).toISOString();

describe('keyHealth', () => {
  it('says nothing about a recent key that is in use and has no near expiry', () => {
    expect(keyHealth({ createdAt: ago(200), lastUsedAt: ago(2), expiresAt: ahead(200) }, NOW)).toBeNull();
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: null, expiresAt: null }, NOW)).toBeNull();
  });

  it('calls an expired key expired, whatever else is true', () => {
    expect(keyHealth({ createdAt: ago(400), lastUsedAt: ago(300), expiresAt: ago(1) }, NOW)).toEqual({ text: 'Expired', tone: 'bad' });
    expect(keyHealth({ createdAt: ago(10), lastUsedAt: ago(1), expiresAt: new Date(NOW).toISOString() }, NOW)?.text).toBe('Expired');
  });

  it('warns from thirty days before expiry, counting the days, and not before', () => {
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: ago(1), expiresAt: ahead(12.5) }, NOW)).toEqual({ text: 'Expires in 12 days', tone: 'warn' });
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: ago(1), expiresAt: ahead(30) }, NOW)?.text).toBe('Expires in 30 days');
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: ago(1), expiresAt: ahead(31.5) }, NOW)).toBeNull();
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: ago(1), expiresAt: ahead(1.2) }, NOW)?.text).toBe('Expires in 1 day');
    expect(keyHealth({ createdAt: ago(5), lastUsedAt: ago(1), expiresAt: ahead(0.4) }, NOW)?.text).toBe('Expires today');
  });

  it('flags a key nothing has used for ninety days, and a key never used that is that old', () => {
    expect(keyHealth({ createdAt: ago(300), lastUsedAt: ago(90) }, NOW)).toEqual({ text: 'Not used for 90 days', tone: 'warn' });
    expect(keyHealth({ createdAt: ago(300), lastUsedAt: ago(89) }, NOW)).toBeNull();
    expect(keyHealth({ createdAt: ago(120), lastUsedAt: null }, NOW)).toEqual({ text: 'Never used, made 120 days ago', tone: 'warn' });
    expect(keyHealth({ createdAt: ago(89), lastUsedAt: null }, NOW)).toBeNull();
  });

  it('puts the expiry warning ahead of the unused one, and ignores dates it cannot read', () => {
    expect(keyHealth({ createdAt: ago(300), lastUsedAt: ago(200), expiresAt: ahead(5) }, NOW)?.text).toBe('Expires in 5 days');
    expect(keyHealth({ createdAt: 'nonsense', lastUsedAt: 'nope', expiresAt: 'nope' }, NOW)).toBeNull();
  });
});
