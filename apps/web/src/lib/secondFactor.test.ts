import { describe, expect, it } from 'vitest';
import { secondFactorBadge } from './secondFactor';

describe('secondFactorBadge', () => {
  it('warns when a person has neither a passkey nor an authenticator app', () => {
    expect(secondFactorBadge({ passkeys: 0, authenticator: false })).toEqual({ text: 'No second factor', warn: true });
  });
  it('names what is set up, with counts', () => {
    expect(secondFactorBadge({ passkeys: 1, authenticator: false })).toEqual({ text: '1 passkey', warn: false });
    expect(secondFactorBadge({ passkeys: 2, authenticator: true })).toEqual({ text: '2 passkeys + authenticator app', warn: false });
    expect(secondFactorBadge({ passkeys: 0, authenticator: true })).toEqual({ text: 'authenticator app', warn: false });
  });
  it('says nothing when the server did not send the fields', () => {
    expect(secondFactorBadge({})).toBeNull();
  });
});
