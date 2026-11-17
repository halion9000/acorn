import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { AnnouncementsView } from './AnnouncementsView';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

describe('Settings, Announcements', () => {
  let rows: unknown[];
  beforeEach(() => {
    rows = [{ id: 'a1', message: 'Maintenance tonight', tone: 'warning', ends_on: '2026-11-20', created_by: 'hal@x' }];
    authFetch.mockReset();
    authFetch.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return json({ id: 'a2', message: 'x', tone: 'info', ends_on: null, created_by: null }, 201);
      if (init?.method === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }));
      return json(rows);
    });
  });

  it('lists what is showing and posts a message with its kind and end day', async () => {
    const user = userEvent.setup();
    render(<AnnouncementsView />);
    expect(await screen.findByTestId('announcement-list')).toHaveTextContent('Maintenance tonight');
    expect(screen.getByTestId('announcement-list')).toHaveTextContent('Warning · until 2026-11-20 · posted by hal@x');
    expect(screen.getByRole('button', { name: 'Post' })).toBeDisabled();
    await user.type(screen.getByLabelText('Message'), 'Welcome to the Calendar');
    await user.selectOptions(screen.getByLabelText('Kind'), 'warning');
    await user.type(screen.getByLabelText('Show until'), '2026-12-01');
    await user.click(screen.getByRole('button', { name: 'Post' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find(([, i]) => i?.method === 'POST');
      expect(JSON.parse(post![1].body)).toEqual({ message: 'Welcome to the Calendar', tone: 'warning', ends_on: '2026-12-01' });
    });
    await waitFor(() => expect(screen.getByLabelText('Message')).toHaveValue(''));
  });

  it('removes one, and says why when posting is refused', async () => {
    const user = userEvent.setup();
    render(<AnnouncementsView />);
    await user.click(await screen.findByRole('button', { name: /Remove: Maintenance tonight/ }));
    await waitFor(() => expect(authFetch.mock.calls.some(([u, i]) => String(u).endsWith('/announcements/a1') && i?.method === 'DELETE')).toBe(true));
    authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json({ detail: '5 announcements are already showing. Remove one first.' }, 409) : json([])));
    await user.type(screen.getByLabelText('Message'), 'One too many');
    await user.click(screen.getByRole('button', { name: 'Post' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('5 announcements are already showing');
    authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json({}, 403) : json([])));
    await user.click(screen.getByRole('button', { name: 'Post' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You need to be a workspace manager');
  });
});
