import { describe, expect, it } from 'vitest';
import { landingFor } from './landing';

describe('landingFor', () => {
  it('sends a client dashboard sign-in to the client dashboard whatever page they asked for', () => {
    expect(landingFor('client_viewer', '/dashboard')).toBe('/client-portal');
    expect(landingFor('client_viewer', '/settings')).toBe('/client-portal');
  });
  it('sends an auditor sign-in to the audit portal whatever page they asked for', () => {
    expect(landingFor('auditor', '/dashboard')).toBe('/audit-portal');
  });
  it('sends a compliance viewer to the Compliance pages, or on to the Compliance page they asked for', () => {
    expect(landingFor('compliance_viewer', '/dashboard')).toBe('/compliance');
    expect(landingFor('compliance_viewer', '/compliance/audits')).toBe('/compliance/audits');
  });
  it('sends everyone else where they were headed', () => {
    expect(landingFor('tenant_admin', '/alerts')).toBe('/alerts');
    expect(landingFor(undefined, '/dashboard')).toBe('/dashboard');
    expect(landingFor(null, '/cases')).toBe('/cases');
  });
});
