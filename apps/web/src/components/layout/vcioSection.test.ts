import { describe, expect, it } from 'vitest';

import { NAV_CATALOG } from './Sidebar';

describe('the vCIO sidebar section', () => {
  it('holds Compliance, Executive Digest and Client Review, and Platform no longer does', () => {
    const labels = (title: string) => NAV_CATALOG.find((s) => s.title === title)?.items.map((i) => i.label);
    expect(labels('vCIO')).toEqual(['Compliance', 'Executive Digest', 'Client Review']);
    const platform = labels('Platform') ?? [];
    for (const moved of ['Compliance', 'Executive Digest', 'Client Review']) expect(platform).not.toContain(moved);
  });

  it('sits between Automation and Platform, and each page keeps its address', () => {
    const titles = NAV_CATALOG.map((s) => s.title);
    expect(titles.indexOf('vCIO')).toBe(titles.indexOf('Automation') + 1);
    expect(titles.indexOf('Platform')).toBe(titles.indexOf('vCIO') + 1);
    const hrefs = NAV_CATALOG.find((s) => s.title === 'vCIO')?.items.map((i) => i.href);
    expect(hrefs).toEqual(['/compliance', '/reports/digest', '/reports/client-review']);
  });
});
