import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { HaloUserRolesPanel, shownTotal } from './HaloUserRoles';

const REPORT = {
  received_at: '2026-11-20T00:00:00Z',
  roles: [{ role: 'Computer User', total: 3 }, { role: 'Primary POC', total: 1 }],
  clients: [
    { client: 'Acme', client_id: '5', counts: { 'Computer User': 2, 'Primary POC': 1 }, total: 3 },
    { client: 'Birch', client_id: '6', counts: { 'Computer User': 1, 'Primary POC': 0 }, total: 1 },
  ],
  all_clients: ['Acme', 'Birch'],
  without_client: 2,
  unread: ['Contractor'],
};

afterEach(() => cleanup());

describe('the HaloPSA user roles', () => {
  it('adds up only the roles that are shown', () => {
    expect(shownTotal({ A: 2, B: 5 }, ['A'])).toBe(2);
    expect(shownTotal({ A: 2 }, ['A', 'Missing'])).toBe(2);
    expect(shownTotal({}, [])).toBe(0);
  });

  it('shows each client by role with a Total, picks out the non-zero counts and says what was left out', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<HaloUserRolesPanel />);
    const table = await screen.findByTestId('halo-roles-table');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Client Name', 'Computer User', 'Primary POC', 'Total']);
    const acme = within(table).getByText('Acme').closest('tr')!;
    expect([...acme.querySelectorAll('td')].map((c) => c.textContent)).toEqual(['Acme', '2', '1', '3']);
    const birch = within(table).getByText('Birch').closest('tr')!;
    expect([...birch.querySelectorAll('td[data-has-value]')].map((c) => c.getAttribute('data-has-value'))).toEqual(['true', 'false']);
    expect(screen.getByText(/Contractor/)).toBeInTheDocument();
    expect(screen.getByText('2 users have no client and are not counted.')).toBeInTheDocument();
  });

  it('follows the roles filter in the columns and the Total, and says so when no client is chosen', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<HaloUserRolesPanel />);
    await screen.findByTestId('halo-roles-table');
    await userEvent.click(screen.getByRole('button', { name: /roles/ }));
    await userEvent.click(screen.getByLabelText(/Primary POC/));
    const table = screen.getByTestId('halo-roles-table');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Client Name', 'Computer User', 'Total']);
    expect([...within(table).getByText('Acme').closest('tr')!.querySelectorAll('td')].map((c) => c.textContent)).toEqual(['Acme', '2', '2']);
    await userEvent.click(screen.getByRole('button', { name: /clients/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('No clients selected')).toBeInTheDocument();
  });

  it('says nothing has arrived when CORE has sent nothing', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: null, roles: [], clients: [], all_clients: [], without_client: 0, unread: [] }) });
    render(<HaloUserRolesPanel />);
    expect(await screen.findByTestId('nothing-yet')).toBeInTheDocument();
  });
});
