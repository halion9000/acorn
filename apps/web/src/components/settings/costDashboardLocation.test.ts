import { describe, expect, it } from 'vitest';

import { NAV_CATALOG } from '@/components/layout/Sidebar';

import { MORE_SETTINGS } from './SettingsView';

describe('where the cost dashboard lives', () => {
  it('is listed under Settings, at its own address', () => {
    expect(MORE_SETTINGS.find((s) => s.href === '/settings/costs')?.label).toBe('Cost dashboard');
  });

  it('is no longer an entry of its own in the sidebar', () => {
    const hrefs = NAV_CATALOG.flatMap((s) => s.items.map((i) => i.href));
    expect(hrefs).not.toContain('/costs');
    expect(hrefs).toContain('/settings');
  });
});
