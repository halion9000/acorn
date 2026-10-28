import { describe, expect, it } from 'vitest';

import { NAV_CATALOG } from './Sidebar';

describe('the sidebar order', () => {
  it('starts with Platform (the SOC dashboards first) and ends with Settings on its own', () => {
    expect(NAV_CATALOG[0].title).toBe('Platform');
    expect(NAV_CATALOG[0].items.map((i) => i.label)).toEqual(['SOC Dashboard', 'SOC Insights', 'Get started', 'User guide', 'MSSP Dashboard', 'Team Analytics', 'SLA Tracking']);
    expect(NAV_CATALOG[0].items[0].href).toBe('/dashboard');
    const last = NAV_CATALOG[NAV_CATALOG.length - 1];
    expect(last.title).toBeUndefined();
    expect(last.items.map((i) => i.label)).toEqual(['Settings']);
    const all = NAV_CATALOG.flatMap((s) => s.items.map((i) => i.label));
    expect(all).not.toContain('Dashboard');
  });
});

describe('the vCIO sidebar section', () => {
  it('holds Compliance, Executive Digest and Client Review, and Platform no longer does', () => {
    const labels = (title: string) => NAV_CATALOG.find((s) => s.title === title)?.items.map((i) => i.label);
    expect(labels('vCIO')).toEqual(['Compliance', 'Executive Digest', 'Client Review']);
    const platform = labels('Platform') ?? [];
    for (const moved of ['Compliance', 'Executive Digest', 'Client Review']) expect(platform).not.toContain(moved);
  });

  it('sits after Automation, and each page keeps its address', () => {
    const titles = NAV_CATALOG.map((s) => s.title);
    expect(titles.indexOf('vCIO')).toBe(titles.indexOf('Automation') + 1);
    const hrefs = NAV_CATALOG.find((s) => s.title === 'vCIO')?.items.map((i) => i.href);
    expect(hrefs).toEqual(['/compliance', '/reports/digest', '/reports/client-review']);
  });
});
