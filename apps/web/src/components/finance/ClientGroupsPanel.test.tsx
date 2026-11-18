import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientGroupsPanel, parseGroupLines } from './ClientGroupsPanel';

const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });
const groups = { groups: [{ primary: 'Asylum / Talking Monkey', members: ['Asylum CC LLC dba Comedy Mothership', 'Talking Monkey, Inc.'] }] };

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? answer({ saved: 2, removed: 1, skipped: 0 }) : answer(groups)));
});

describe('reading pasted groups', () => {
  it('splits at the last comma, or at a tab or semicolon when there is one, and skips blank and one-part lines', () => {
    const text = ['Talking Monkey, Inc., Asylum / Talking Monkey', '"Higher Primate (c/o Level Four, LLC)"\tAsylum / Talking Monkey', 'GHA; Commissions', '', 'lonely line'].join('\n');
    expect(parseGroupLines(text)).toEqual([
      { name: 'Talking Monkey, Inc.', primary: 'Asylum / Talking Monkey' },
      { name: 'Higher Primate (c/o Level Four, LLC)', primary: 'Asylum / Talking Monkey' },
      { name: 'GHA', primary: 'Commissions' },
    ]);
  });
});

describe('the client groups panel', () => {
  it('lists each group with its names', async () => {
    render(<ClientGroupsPanel />);
    const g = await screen.findByTestId('group');
    expect(g).toHaveTextContent('Asylum / Talking Monkey');
    expect(g).toHaveTextContent('Asylum CC LLC dba Comedy Mothership; Talking Monkey, Inc.');
  });

  it('files pasted names and says how many, and ungroups a group by sending its names with no Primary Name', async () => {
    render(<ClientGroupsPanel />);
    await screen.findByTestId('group');
    fireEvent.change(screen.getByLabelText('Names to file under a Primary Name'), { target: { value: 'GHA, Commissions\nGHA Technologies, Commissions' } });
    await userEvent.click(screen.getByRole('button', { name: 'File 2 names' }));
    expect(await screen.findByTestId('groups-note')).toHaveTextContent('2 names filed, 1 taken out of their group.');
    const first = authFetch.mock.calls.find(([, i]) => i?.method === 'PUT')!;
    expect(first[0]).toBe('/api/v1/finance/client-groups/import');
    expect(JSON.parse(first[1].body)).toEqual({ rows: [{ name: 'GHA', primary: 'Commissions' }, { name: 'GHA Technologies', primary: 'Commissions' }] });
    await userEvent.click(within(await screen.findByTestId('group')).getByRole('button', { name: 'Take the names out of Asylum / Talking Monkey' }));
    await waitFor(() => expect(authFetch.mock.calls.filter(([, i]) => i?.method === 'PUT')).toHaveLength(2));
    expect(JSON.parse(authFetch.mock.calls.filter(([, i]) => i?.method === 'PUT')[1]![1].body)).toEqual({ rows: [{ name: 'Asylum CC LLC dba Comedy Mothership', primary: '' }, { name: 'Talking Monkey, Inc.', primary: '' }] });
  });
});
