import { describe, expect, it } from 'vitest';

import { NAV_CATALOG } from './Sidebar';

describe('the sidebar order', () => {
  it('starts with Platform (the SOC dashboards first) and ends with Settings on its own', () => {
    expect(NAV_CATALOG[0].title).toBe('Platform');
    expect(NAV_CATALOG[0].items.map((i) => i.label)).toEqual(['SOC Dashboard', 'SOC Insights', 'Get started', 'Leafy', 'MSSP Dashboard', 'Team Analytics', 'SLA Tracking']);
    expect(NAV_CATALOG[0].items[0].href).toBe('/dashboard');
    const last = NAV_CATALOG[NAV_CATALOG.length - 1];
    expect(last.title).toBeUndefined();
    expect(last.items.map((i) => i.label)).toEqual(['Settings']);
    const all = NAV_CATALOG.flatMap((s) => s.items.map((i) => i.label));
    expect(all).not.toContain('Dashboard');
    expect(all.filter((l) => l === 'Leafy')).toHaveLength(1);
    expect(NAV_CATALOG.find((s) => s.title === 'Intelligence')?.items.map((i) => i.label)).not.toContain('Leafy');
    expect(all).not.toContain('User guide');
    expect(NAV_CATALOG.flatMap((s) => s.items).some((i) => i.href === '/guide')).toBe(false);
  });
});

describe('the Compliance and vCIO sidebar sections', () => {
  const labels = (title: string) => NAV_CATALOG.find((s) => s.title === title)?.items.map((i) => i.label);

  it('Compliance is a section of its own with the pages that are built, and vCIO no longer holds it', () => {
    expect(labels('Compliance')).toEqual(['Overview', 'Frameworks', 'Controls', 'Policies', 'Risk Management', 'Vendors', 'Access Reviews', 'Questionnaires', 'Asset Inventory']);
    expect(labels('vCIO')).toEqual(['Executive Digest', 'Client Review', 'Client Risk Score']);
    const platform = labels('Platform') ?? [];
    for (const moved of ['Compliance', 'Executive Digest', 'Client Review', 'Client Risk Score']) expect(platform).not.toContain(moved);
  });

  it('Compliance sits after Automation and before vCIO, and each page keeps its address', () => {
    const titles = NAV_CATALOG.map((s) => s.title);
    expect(titles.indexOf('Compliance')).toBe(titles.indexOf('Automation') + 1);
    expect(titles.indexOf('vCIO')).toBe(titles.indexOf('Compliance') + 1);
    expect(NAV_CATALOG.find((s) => s.title === 'Compliance')?.items.map((i) => i.href)).toEqual(['/compliance', '/compliance/frameworks', '/compliance/controls', '/compliance/policies', '/compliance/risk-register', '/compliance/vendors', '/compliance/access-reviews', '/compliance/questionnaires', '/inventory']);
    expect(NAV_CATALOG.find((s) => s.title === 'vCIO')?.items.map((i) => i.href)).toEqual(['/reports/digest', '/reports/client-review', '/vcio-risk-scoring']);
  });
});
