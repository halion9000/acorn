import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { JoinersLeavers } from './JoinersLeavers';

const ok = (b: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => b });
const DATA = {
  days: 30,
  recorded_since: '2026-11-18T10:00:00+00:00',
  joiners: [{ client: 'Acme', upn: 'new@acme.test', name: 'New Person', when: '2026-11-20T00:00:00+00:00' }],
  leavers: [{ client: 'Birch', upn: 'gone@birch.test', name: '', when: '2026-11-21T00:00:00+00:00' }],
};

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(() => ok(DATA));
});

describe('JoinersLeavers', () => {
  it('is closed until asked, and reads nothing from the API while closed', async () => {
    render(<JoinersLeavers />);
    expect(screen.queryByTestId('joiners')).toBeNull();
    expect(authFetch).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Joiners and leavers/ }));
    expect(await screen.findByTestId('joiners')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /Joiners and leavers/ }));
    expect(screen.queryByTestId('joiners')).toBeNull();
  });

  it('lists who joined and who left with the day, and says how the join day is worked out', async () => {
    render(<JoinersLeavers />);
    await userEvent.click(screen.getByRole('button', { name: /Joiners and leavers/ }));
    expect(within(await screen.findByTestId('joiners')).getByText('new@acme.test')).toBeTruthy();
    expect(within(screen.getByTestId('leavers')).getByText('2026-11-21')).toBeTruthy();
    expect(screen.getByText(/first saw the account/)).toBeTruthy();
    expect(screen.getByText(/Recorded since 2026-11-18/)).toBeTruthy();
  });

  it('asks again for another period, and shows a failed read', async () => {
    render(<JoinersLeavers />);
    await userEvent.click(screen.getByRole('button', { name: /Joiners and leavers/ }));
    await screen.findByTestId('joiners');
    await userEvent.selectOptions(screen.getByLabelText(/Period/), '90');
    expect(authFetch).toHaveBeenLastCalledWith('/api/v1/identity/joiners-leavers?days=90');
    authFetch.mockImplementation(() => Promise.resolve({ ok: false, status: 500, json: async () => ({}) }));
    await userEvent.selectOptions(screen.getByLabelText(/Period/), '7');
    expect(await screen.findByText('The API answered 500')).toBeTruthy();
  });

  it('says so when nothing happened', async () => {
    authFetch.mockImplementation(() => ok({ days: 30, joiners: [], leavers: [], recorded_since: null }));
    render(<JoinersLeavers />);
    await userEvent.click(screen.getByRole('button', { name: /Joiners and leavers/ }));
    expect((await screen.findAllByText('None in this period.')).length).toBe(2);
    expect(screen.getByText(/Nothing is recorded yet/)).toBeTruthy();
  });
});
