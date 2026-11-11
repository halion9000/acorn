import { describe, expect, it } from 'vitest';
import { FALLBACK_KINDS, auditKindOptions } from './auditKinds';

describe('auditKindOptions', () => {
  it('offers exactly the kinds the server says exist, with counts, in the order given, and names the ones it knows', () => {
    const out = auditKindOptions([
      { prefix: 'alerts:', count: 180 },
      { prefix: 'role:', count: 3 },
      { prefix: 'tenant:', count: 1 },
      { prefix: 'api_keys:', count: 2 },
    ]);
    expect(out).toEqual([
      { value: 'alerts:', label: 'Alerts (180)' },
      { value: 'role:', label: 'Roles (3)' },
      { value: 'tenant:', label: 'Members and access (1)' },
      { value: 'api_keys:', label: 'Api keys (2)' },
    ]);
  });

  it('falls back to the usual kinds when the server has not answered or answered with nothing, and ignores a malformed prefix', () => {
    expect(auditKindOptions(undefined)).toBe(FALLBACK_KINDS);
    expect(auditKindOptions(null)).toBe(FALLBACK_KINDS);
    expect(auditKindOptions([])).toBe(FALLBACK_KINDS);
    expect(auditKindOptions([{ prefix: 'nocolon', count: 1 }, { prefix: 'cases:', count: 2 }])).toEqual([{ value: 'cases:', label: 'Cases (2)' }]);
  });

  it('every fallback kind is a prefix with a colon, so it can be sent as the filter', () => {
    for (const k of FALLBACK_KINDS) expect(k.value.endsWith(':')).toBe(true);
  });
});
