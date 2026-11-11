import { describe, expect, it } from 'vitest';
import { membersCsvText, recoveryCodesWarning, secondFactorBadge, withoutSecondFactor } from './secondFactor';

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

describe('withoutSecondFactor', () => {
  it('lists active people who have neither a passkey nor an authenticator app, and not those on an older server or disabled', () => {
    const rows = [
      { id: 'a', passkeys: 0, authenticator: false },
      { id: 'b', passkeys: 1, authenticator: false },
      { id: 'c', passkeys: 0, authenticator: true },
      { id: 'd' },
      { id: 'e', passkeys: 0, authenticator: false, is_active: false },
    ];
    expect(withoutSecondFactor(rows).map((r) => r.id)).toEqual(['a']);
  });
});

describe('recoveryCodesWarning', () => {
  it('says nothing while there are enough, then says how few are left, and says plainly when none are', () => {
    expect(recoveryCodesWarning(10)).toBeNull();
    expect(recoveryCodesWarning(3)).toBeNull();
    expect(recoveryCodesWarning(2)).toBe('Only 2 recovery codes left. Make new ones before you run out.');
    expect(recoveryCodesWarning(1)).toBe('Only 1 recovery code left. Make new ones before you run out.');
    expect(recoveryCodesWarning(0)).toMatch(/^No recovery codes left/);
  });
});

describe('membersCsvText', () => {
  it('has a header and one row per member with the second factor spelled out, and a formula-looking name made safe', () => {
    const text = membersCsvText([
      { account_name: 'hal.owner', username: 'Hal', email: 'hal@x.test', role: 'tenant_admin', is_active: true, last_login: '2026-11-10T09:00:00Z', passkeys: 2, authenticator: true },
      { account_name: 'bare', username: '=HYPERLINK("http://evil")', email: null, role: 'custom', custom_roles: [{ name: 'Reader' }, { name: 'Billing' }], is_active: false, passkeys: 0, authenticator: false },
      { account_name: 'older', role: 'viewer' },
    ]);
    const lines = text.replace('\uFEFF', '').split('\r\n');
    expect(lines[0]).toBe('Account,Name,Email,Role,Custom roles,Active,Last sign-in,Passkeys,Authenticator app,Second factor');
    expect(lines[1]).toBe('hal.owner,Hal,hal@x.test,tenant_admin,,yes,2026-11-10T09:00:00Z,2,yes,2 passkeys + authenticator app');
    expect(lines[2]).toBe('bare,"\'=HYPERLINK(""http://evil"")",,custom,Reader; Billing,no,,0,no,No second factor');
    expect(lines[3]).toBe('older,,,viewer,,yes,,,,not reported');
  });
});
