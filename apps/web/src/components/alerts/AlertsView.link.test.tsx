import { describe, expect, it } from 'vitest';

import { filtersFromUrl, filtersToUrl } from './AlertsView';

describe('the address that opens the alert list as it is now', () => {
  it('writes only what is not the default, and reading it back gives the same filters', () => {
    expect(filtersToUrl({ page: 1, pageSize: 25, status: 'open' })).toBe('');
    expect(filtersToUrl({ page: 1, pageSize: 25 })).toBe('status=all');
    const all = { page: 1, pageSize: 25, status: 'new', device: 'PC-1', user: 'a@x.com', clientId: 'c-1', severity: 'high', source: 'huntress', ticket: 'none' as const, search: 'printer' };
    const q = filtersToUrl(all);
    expect(q).toBe('status=new&device=PC-1&user=a%40x.com&client=c-1&severity=high&source=huntress&ticket=none&q=printer');
    expect(filtersFromUrl(new URLSearchParams(q))).toEqual(all);
    expect(filtersFromUrl(new URLSearchParams(filtersToUrl({ page: 1, pageSize: 25 })))).toEqual({ page: 1, pageSize: 25 });
  });

  it('leaves out what an address cannot carry: a date range, an assignee, a kind', () => {
    expect(filtersToUrl({ page: 3, pageSize: 25, status: 'open', assignee: 'me', category: 'vulnerability', collapse: true, startTime: '2026-01-01' })).toBe('');
  });
});
