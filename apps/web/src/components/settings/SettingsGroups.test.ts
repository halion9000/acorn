import { describe, expect, it } from 'vitest';
import { MORE_SETTINGS, SETTINGS_GROUPS, groupedSettings } from './SettingsView';

const tabs = [
  { id: 'profile', label: 'Profile', description: '' },
  { id: 'appearance', label: 'Appearance', description: '' },
  { id: 'azure-spend', label: 'Azure spend', description: '' },
  { id: 'brand-new', label: 'Brand new', description: '' },
] as const;

describe('settings groups', () => {
  it('place every page of More settings in exactly one group, so a new page cannot be left out', () => {
    const placed = SETTINGS_GROUPS.flatMap((g) => g.items);
    for (const m of MORE_SETTINGS) expect(placed.filter((k) => k === m.href), m.href).toHaveLength(1);
    expect(new Set(placed).size).toBe(placed.length);
  });

  it('show only the tabs a person may use, in group order, with no empty group', () => {
    const groups = groupedSettings([...tabs].filter((t) => t.id !== 'azure-spend') as never);
    const titles = groups.map((g) => g.title);
    expect(titles[0]).toBe('Your account');
    const names = groups.flatMap((g) => g.entries.map((e) => e.label));
    expect(names).not.toContain('Azure spend');
    expect(groups.every((g) => g.entries.length > 0)).toBe(true);
    expect(groups.find((g) => g.title === 'Your account')!.entries.map((e) => e.label)).toEqual(['Profile', 'Appearance']);
  });

  it('keep a tab or page nobody placed under More instead of dropping it', () => {
    const groups = groupedSettings([...tabs] as never);
    const more = groups.find((g) => g.title === 'More');
    expect(more?.entries.map((e) => e.label)).toEqual(['Brand new']);
  });

  it('give each link its address and each tab its id', () => {
    const groups = groupedSettings([...tabs] as never);
    const clients = groups.find((g) => g.title === 'Clients')!;
    expect(clients.entries.every((e) => e.kind === 'link' && e.href.startsWith('/settings/'))).toBe(true);
    const account = groups.find((g) => g.title === 'Your account')!;
    expect(account.entries[0]).toMatchObject({ kind: 'tab', id: 'profile' });
  });
});
