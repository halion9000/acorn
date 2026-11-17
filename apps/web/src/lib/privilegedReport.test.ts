import { describe, expect, it } from 'vitest';
import type { IdentityPerson } from '@/lib/api';
import { privilegedCsv, privilegedRows } from '@/lib/privilegedReport';

const person = (over: Partial<IdentityPerson>): IdentityPerson => ({
  key: 'k', client_id: 'c', client_name: 'Acme', email: 'a@acme.com', display_name: 'A', kind: 'member', enabled: true, admin: true, licensed: true, mfa: 'covered', mfa_methods: null,
  signin_state: 'active', days_since_signin: 2, tools: ['m365'], sources: [], open_alerts: 0, top_severity: null, ...over,
});

describe('the privileged account list', () => {
  it('lists only administrators, riskiest first: enabled with no Multi-Factor, then stale sign-ins, disabled last', () => {
    const rows = privilegedRows([
      person({ email: 'fine@acme.com' }),
      person({ email: 'off@acme.com', enabled: false, mfa: 'none' }),
      person({ email: 'nomfa@acme.com', mfa: 'none' }),
      person({ email: 'stale@acme.com', signin_state: 'inactive', days_since_signin: 200 }),
      person({ email: 'user@acme.com', admin: false, mfa: 'none' }),
    ]);
    expect(rows.map((r) => r.email)).toEqual(['nomfa@acme.com', 'stale@acme.com', 'fine@acme.com', 'off@acme.com']);
    expect(rows[0]!.flag).toBe('no Multi-Factor');
    expect(rows[1]!.flag).toBe('no sign-in for 90+ days');
    expect(rows[2]!.flag).toBe('');
    expect(rows[3]!.flag).toBe('disabled');
  });

  it('says unknown where the data does not say, and words each Multi-Factor state', () => {
    const [r] = privilegedRows([person({ enabled: null, mfa: 'registered_not_required', signin_state: null, days_since_signin: null })]);
    expect([r!.enabled, r!.mfa, r!.signinState, r!.daysSinceSignin]).toEqual(['unknown', 'registered, not required', 'unknown', null]);
  });

  it('writes a CSV with a header, quoting, and a safe start for anything that looks like a formula', () => {
    const csv = privilegedCsv(privilegedRows([person({ display_name: '=SUM(1,2)', client_name: 'Smith, Jones & Co', tools: ['m365', 'google'] })]));
    const lines = csv.split('\r\n');
    expect(lines[0]).toBe('client,email,name,enabled,multi-factor,sign-in,days since sign-in,tools,flag');
    expect(lines[1]).toBe('"Smith, Jones & Co",a@acme.com,"\'=SUM(1,2)",yes,covered,active,2,m365 google,');
    expect(privilegedCsv([])).toBe(lines[0] + '\r\n');
  });
});
