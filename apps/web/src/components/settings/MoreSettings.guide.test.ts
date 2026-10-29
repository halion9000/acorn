import { describe, expect, it } from 'vitest';

import { MORE_SETTINGS } from './SettingsView';

describe('the more-settings list', () => {
  it('has the ACORN Setup Guide, at its Settings address, once', () => {
    const entries = MORE_SETTINGS.filter((m) => m.label === 'ACORN Setup Guide');
    expect(entries).toHaveLength(1);
    expect(entries[0].href).toBe('/settings/guide');
    expect(MORE_SETTINGS.some((m) => m.label === 'User guide')).toBe(false);
  });
});
