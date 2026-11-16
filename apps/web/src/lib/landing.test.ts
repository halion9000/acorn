import { describe, expect, it } from 'vitest';
import { landingFor } from './landing';

describe('landingFor', () => {
  it('sends a client dashboard sign-in to the client dashboard whatever page they asked for', () => {
    expect(landingFor('client_viewer', '/dashboard')).toBe('/client-portal');
    expect(landingFor('client_viewer', '/settings')).toBe('/client-portal');
  });
  it('sends everyone else where they were headed', () => {
    expect(landingFor('tenant_admin', '/alerts')).toBe('/alerts');
    expect(landingFor(undefined, '/dashboard')).toBe('/dashboard');
    expect(landingFor(null, '/cases')).toBe('/cases');
  });
});
