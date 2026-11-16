import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth-session', () => ({ authFetch: vi.fn() }));

import { warrantyOf } from './DevicesView';

const device = (details: Record<string, unknown>[]) => ({ sources: details.map((d, i) => ({ vendor: 'ninjaone', external_id: String(i), details: d })) }) as never;

describe('warrantyOf', () => {
  it('reads the end date a feed reported and the maker lookup page', () => {
    expect(warrantyOf(device([{ warranty_end: '2027-03-04T00:00:00Z', warranty_lookup_url: 'https://www.dell.com/support/home/en-us/product-support/servicetag/ABC1234/overview' }]))).toEqual({
      end: '2027-03-04',
      lookupUrl: 'https://www.dell.com/support/home/en-us/product-support/servicetag/ABC1234/overview',
    });
  });
  it('knows nothing when no feed said anything', () => {
    expect(warrantyOf(device([{}, { url: 'https://x.example' }]))).toEqual({ end: null, lookupUrl: null });
  });
  it('refuses a date that is not a date and a link that is not plain https', () => {
    expect(warrantyOf(device([{ warranty_end: 'soon', warranty_lookup_url: 'javascript:alert(1)' }]))).toEqual({ end: null, lookupUrl: null });
    expect(warrantyOf(device([{ warranty_lookup_url: 'http://insecure.example/x' }])).lookupUrl).toBeNull();
  });
  it('takes the first source that has the value', () => {
    expect(warrantyOf(device([{}, { warranty_end: '2026-12-31' }])).end).toBe('2026-12-31');
  });
});
