import { describe, expect, it } from 'vitest';
import { aliasesOf, myVendors, ownedBy } from '@/lib/vendorOwner';

const hal = { email: 'Hal@GoLiveOak.com', account_name: 'hal.k', username: null };

describe('whose vendor it is', () => {
  it('matches an owner written as the e-mail address, its first part, the account name, or "Name <address>", in any letter case', () => {
    expect(ownedBy('hal@goliveoak.com', hal)).toBe(true);
    expect(ownedBy('HAL', hal)).toBe(true);
    expect(ownedBy('Hal.K', hal)).toBe(true);
    expect(ownedBy('Hal <hal@goliveoak.com>', hal)).toBe(true);
  });
  it('does not match another person, a blank owner, or a name that only contains a part of theirs', () => {
    expect(ownedBy('Hallie', hal)).toBe(false);
    expect(ownedBy('', hal)).toBe(false);
    expect(ownedBy(null, hal)).toBe(false);
    expect(ownedBy('ann@goliveoak.com', hal)).toBe(false);
    expect(ownedBy('anything', {})).toBe(false);
  });
  it('ignores one-letter names and lists each alias once', () => {
    expect(aliasesOf({ email: 'a@x.com', account_name: 'a', username: 'a@x.com' })).toEqual(['a@x.com']);
  });
  it('picks a person’s vendors out of the list, and nobody’s when the person is not known', () => {
    const v = [{ name: 'A', owner: 'hal' }, { name: 'B', owner: 'ann' }, { name: 'C', owner: null }];
    expect(myVendors(v, hal).map((x) => x.name)).toEqual(['A']);
    expect(myVendors(v, null)).toEqual([]);
  });
});
