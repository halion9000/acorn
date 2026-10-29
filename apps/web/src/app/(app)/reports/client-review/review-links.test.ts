import { describe, expect, it } from 'vitest';
import { reviewLink } from './review-links';

const ID = 'c-1';

describe('reviewLink', () => {
  it('names the people count for the Multi-Factor questions and lands on that client list', () => {
    expect(reviewLink('mfa_everyone', 'not_met', ID, { mfa: { without_mfa: 7 } })).toEqual({
      label: 'See the 7 people without Multi-Factor',
      href: '/settings/mfa?client=c-1&which=without',
    });
    expect(reviewLink('mfa_admins', 'not_met', ID, { mfa: { admins_without_mfa: 2 } })?.href).toBe('/settings/mfa?client=c-1&which=admins');
    expect(reviewLink('mfa_everyone', 'partly', ID)?.label).toBe('See the people without Multi-Factor');
  });

  it('sends a tool question to the computers missing that tool, for that client', () => {
    expect(reviewLink('edr', 'partly', ID)?.href).toBe('/devices?client=c-1&missing=huntress');
    expect(reviewLink('management', 'not_met', ID)?.href).toBe('/devices?client=c-1&missing=ninjaone');
    expect(reviewLink('dns', 'not_met', ID)?.href).toBe('/devices?client=c-1&missing=dnsfilter');
    expect(reviewLink('privilege', 'partly', ID)?.href).toBe('/devices?client=c-1&missing=autoelevate&os=windows');
    expect(reviewLink('agents_reporting', 'not_met', ID)?.href).toBe('/devices?client=c-1&stale=1');
  });

  it('gives no link to an answer that is met or not known, or to a question no page answers', () => {
    expect(reviewLink('edr', 'met', ID)).toBeNull();
    expect(reviewLink('edr', 'unknown', ID)).toBeNull();
    expect(reviewLink('ir_plan', 'not_met', ID)).toBeNull();
  });

  it('encodes the client id', () => {
    expect(reviewLink('edr', 'not_met', 'a b&c')?.href).toBe('/devices?client=a%20b%26c&missing=huntress');
  });
});
