import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientGroupsPanel, filterNames, groupChanges } from './ClientGroupsPanel';

const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });
const groups = { groups: [{ primary: 'Asylum / Talking Monkey', members: ['Asylum CC LLC dba Comedy Mothership', 'Talking Monkey, Inc.'] }] };
const names = {
  names: [
    { name: 'Asylum CC LLC dba Comedy Mothership', group: 'Asylum / Talking Monkey' },
    { name: 'Talking Monkey, Inc.', group: 'Asylum / Talking Monkey' },
    { name: 'Higher Primate', group: null },
    { name: 'Sandler Corp', group: null },
    { name: 'GHA', group: 'Commissions' },
  ],
};
const puts = () => authFetch.mock.calls.filter(([, i]) => i?.method === 'PUT').map(([, i]) => JSON.parse(i.body));

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((u: string, init?: RequestInit) => (init?.method ? answer({ saved: 2, removed: 1, skipped: 0 }) : answer(u.includes('client-names') ? names : groups)));
});

describe('groupChanges', () => {
  const orig = { primary: 'Asylum', members: ['A', 'B'] };
  it('sends only the names added, and an empty Primary Name for each one taken out', () => {
    expect(groupChanges(orig, 'Asylum', ['A', 'C'])).toEqual([{ name: 'C', primary: 'Asylum' }, { name: 'B', primary: '' }]);
  });
  it('sends every ticked name again when the Primary Name changed, and a new group sends all its names', () => {
    expect(groupChanges(orig, 'Asylum Group', ['A', 'B'])).toEqual([{ name: 'A', primary: 'Asylum Group' }, { name: 'B', primary: 'Asylum Group' }]);
    expect(groupChanges(null, 'New', ['X', 'Y'])).toEqual([{ name: 'X', primary: 'New' }, { name: 'Y', primary: 'New' }]);
    expect(groupChanges(orig, 'Asylum', ['A', 'B'])).toEqual([]);
  });
});

describe('filterNames', () => {
  it('finds names in any case and lists the ticked ones first', () => {
    const list = names.names;
    expect(filterNames(list, 'mon', new Set()).map((n) => n.name)).toEqual(['Talking Monkey, Inc.']);
    expect(filterNames(list, '', new Set(['Sandler Corp'])).map((n) => n.name)[0]).toBe('Sandler Corp');
  });
});

describe('the client groups panel', () => {
  it('lists each group with its names and an Edit and an Ungroup button', async () => {
    render(<ClientGroupsPanel />);
    const g = await screen.findByTestId('group');
    expect(g).toHaveTextContent('Asylum CC LLC dba Comedy Mothership; Talking Monkey, Inc.');
    expect(within(g).getByRole('button', { name: 'Edit Asylum / Talking Monkey' })).toBeTruthy();
  });

  it('edits a group by ticking and un-ticking names, and sends only what changed', async () => {
    render(<ClientGroupsPanel />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Asylum / Talking Monkey' }));
    const picker = await screen.findByTestId('group-picker');
    expect((within(picker).getByLabelText('Talking Monkey, Inc.') as HTMLInputElement).checked).toBe(true);
    expect((within(picker).getByLabelText('Higher Primate') as HTMLInputElement).checked).toBe(false);
    await userEvent.click(within(picker).getByLabelText('Higher Primate'));
    await userEvent.click(within(picker).getByLabelText('Talking Monkey, Inc.'));
    await userEvent.click(within(picker).getByRole('button', { name: 'Save group' }));
    expect(await screen.findByTestId('groups-note')).toHaveTextContent('2 names filed, 1 taken out of their group.');
    expect(puts()[0]).toEqual({ rows: [{ name: 'Higher Primate', primary: 'Asylum / Talking Monkey' }, { name: 'Talking Monkey, Inc.', primary: '' }] });
  });

  it('makes a new group from a Primary Name and ticked names, finding names with the search box, and says when a name is in another group', async () => {
    render(<ClientGroupsPanel />);
    await userEvent.click(await screen.findByRole('button', { name: 'New group' }));
    const picker = await screen.findByTestId('group-picker');
    expect(within(picker).getByRole('button', { name: 'Save group' })).toBeDisabled();
    expect(within(picker).getByText('(now in Commissions)')).toBeTruthy();
    await userEvent.type(within(picker).getByLabelText('Find a name'), 'sandl');
    await userEvent.click(within(picker).getByLabelText('Sandler Corp'));
    await userEvent.type(within(picker).getByLabelText('Primary Name'), 'Commissions');
    await userEvent.click(within(picker).getByRole('button', { name: 'Save group' }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({ rows: [{ name: 'Sandler Corp', primary: 'Commissions' }] });
  });

  it('ungroups a group by sending its names with no Primary Name', async () => {
    render(<ClientGroupsPanel />);
    await userEvent.click(within(await screen.findByTestId('group')).getByRole('button', { name: 'Take the names out of Asylum / Talking Monkey' }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({ rows: [{ name: 'Asylum CC LLC dba Comedy Mothership', primary: '' }, { name: 'Talking Monkey, Inc.', primary: '' }] });
  });
});
