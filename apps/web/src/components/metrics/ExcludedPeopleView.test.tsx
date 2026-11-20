import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ExcludedPeopleView, toSave } from './ExcludedPeopleView';

afterEach(() => cleanup());

describe('the Metrics people settings', () => {
  it('keeps a name that is no longer in the data, adds the ticked ones and drops repeats', () => {
    expect(toSave(new Set(['Vic Cio', 'dan kemp']), ['Dan Kemp', 'Vic Cio'], ['Dan Kemp', 'Gone Person'])).toEqual(['dan kemp', 'Gone Person', 'Vic Cio']);
  });

  it('shows the excluded engineers ticked, saves the new choice and says how many are excluded', async () => {
    const put: unknown[] = [];
    authFetch.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        put.push(JSON.parse(String(init.body)));
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ excluded: ['Dan Kemp', 'Vic Cio'] }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ excluded: ['dan kemp'], engineers: ['Dan Kemp', 'Vic Cio'] }) });
    });
    render(<ExcludedPeopleView />);
    const dan = (await screen.findByLabelText('Dan Kemp')) as HTMLInputElement;
    expect(dan.checked).toBe(true);
    expect((screen.getByLabelText('Vic Cio') as HTMLInputElement).checked).toBe(false);
    await userEvent.click(screen.getByLabelText('Vic Cio'));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved: 2 excluded.')).toBeInTheDocument();
    expect(put).toEqual([{ excluded: ['Dan Kemp', 'Vic Cio'] }]);
  });

  it('says so when changing it is not allowed', async () => {
    authFetch.mockImplementation((_url: string, init?: RequestInit) => Promise.resolve(init?.method === 'PUT' ? { ok: false, status: 403, json: () => Promise.resolve({}) } : { ok: true, status: 200, json: () => Promise.resolve({ excluded: [], engineers: ['Dan Kemp'] }) }));
    render(<ExcludedPeopleView />);
    await screen.findByLabelText('Dan Kemp');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Changing this needs the manage permission.')).toBeInTheDocument();
  });
});
