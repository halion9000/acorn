import { describe, expect, it } from 'vitest';

import { filterSettingsGroups, groupedSettings } from './SettingsView';

const tabs = [
  { id: 'profile' as const, label: 'Profile', description: 'Your name, password and authenticator app' },
  { id: 'api-keys' as const, label: 'API keys', description: 'Keys programs use to call A.C.O.R.N' },
];

describe('filterSettingsGroups', () => {
  const groups = groupedSettings(tabs);
  it('keeps everything for an empty or blank search', () => {
    expect(filterSettingsGroups(groups, '')).toBe(groups);
    expect(filterSettingsGroups(groups, '   ')).toBe(groups);
  });
  it('finds an entry by a word in its name or description, whatever the letter case, and needs every word', () => {
    const byDesc = filterSettingsGroups(groups, 'AUTHENTICATOR');
    expect(byDesc.flatMap((g) => g.entries.map((e) => e.label))).toEqual(['Profile']);
    const both = filterSettingsGroups(groups, 'keys call');
    expect(both.flatMap((g) => g.entries.map((e) => e.label))).toEqual(['API keys']);
    expect(filterSettingsGroups(groups, 'keys authenticator')).toEqual([]);
  });
  it('drops a group with nothing left, and finds a setting that is a link as well as a tab', () => {
    const out = filterSettingsGroups(groups, 'password');
    expect(out.every((g) => g.entries.length > 0)).toBe(true);
    expect(out.length).toBeLessThan(groups.length);
    expect(filterSettingsGroups(groups, 'nothing-matches-this-xyz')).toEqual([]);
    const link = groups.flatMap((g) => g.entries).find((e) => e.kind === 'link');
    expect(link).toBeDefined();
    expect(filterSettingsGroups(groups, link!.label).flatMap((g) => g.entries).some((e) => e.kind === 'link' && e.href === (link as { href: string }).href)).toBe(true);
  });
});
