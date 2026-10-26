import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientCleanup } from './ClientCleanup';

const reply = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) });
const empty = (id: string, name: string) => ({ id, name, devices: 0, alerts: 0, cases: 0, tool_clients: 0 });

beforeEach(() => authFetch.mockReset());

describe('ClientCleanup suspect mappings', () => {
  it('lists mapped tool clients whose names look unrelated, and shows nothing when there are none or the check fails', async () => {
    authFetch.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith('/suspect-mappings')
          ? reply([{ alias_id: 'x1', vendor: 'ninjaone', vendor_client_name: 'Harbor Legal', client_id: 'c1', client_name: 'Zephyr Hotels', score: 0.1 }])
          : reply({ checked: 3, empty: [] }),
      ),
    );
    const { unmount } = render(<ClientCleanup />);
    const rows = await screen.findAllByTestId('suspect-mapping');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('ninjaone: Harbor Legal is mapped to Zephyr Hotels');
    unmount();
    authFetch.mockImplementation((url: string) => Promise.resolve(String(url).endsWith('/suspect-mappings') ? reply({}, false) : reply({ checked: 3, empty: [] })));
    render(<ClientCleanup />);
    await screen.findByTestId('checked');
    expect(screen.queryByTestId('suspect-mappings')).toBeNull();
  });
});

describe('ClientCleanup', () => {
  it('lists the empty clients and how many were checked', async () => {
    authFetch.mockResolvedValue(reply({ checked: 12, empty: [empty('a', 'Old Dental'), empty('b', 'Test Co')] }));
    render(<ClientCleanup />);
    expect(await screen.findByTestId('checked')).toHaveTextContent('12 clients checked, 2 empty.');
    expect(screen.getAllByTestId('empty-client')).toHaveLength(2);
  });

  it('asks before archiving, archives only that client, then reloads the list', async () => {
    let archived = false;
    authFetch.mockImplementation((url: string, init?: { method?: string }) => {
      if (init?.method === 'POST') {
        archived = true;
        return Promise.resolve(reply({ removed: true, name: 'Old Dental (archived)', reason: null }));
      }
      return Promise.resolve(reply({ checked: 12, empty: archived ? [empty('b', 'Test Co')] : [empty('a', 'Old Dental'), empty('b', 'Test Co')] }));
    });
    render(<ClientCleanup />);
    await screen.findAllByTestId('empty-client');
    await userEvent.click(screen.getAllByRole('button', { name: 'Archive' })[0]);
    expect(authFetch).not.toHaveBeenCalledWith(expect.stringContaining('/archive'), expect.anything());
    await userEvent.click(screen.getByRole('button', { name: 'Archive Old Dental' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/mssp/tenants/a/archive', { method: 'POST' }));
    await waitFor(() => expect(screen.getAllByTestId('empty-client')).toHaveLength(1));
    expect(screen.getByTestId('empty-client')).toHaveTextContent('Test Co');
  });

  it('can be cancelled without archiving', async () => {
    authFetch.mockResolvedValue(reply({ checked: 1, empty: [empty('a', 'Old Dental')] }));
    render(<ClientCleanup />);
    await userEvent.click(await screen.findByRole('button', { name: 'Archive' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument();
    // The cleanup report and the mapping check were each read once, and nothing was archived.
    expect(authFetch.mock.calls.map((c) => c[0]).sort()).toEqual(['/api/v1/mssp/clients/cleanup', '/api/v1/mssp/clients/suspect-mappings']);
    expect(authFetch.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(false);
  });

  it('says so when nothing is empty, and shows an error plainly', async () => {
    authFetch.mockResolvedValue(reply({ checked: 5, empty: [] }));
    const { unmount } = render(<ClientCleanup />);
    expect(await screen.findByTestId('none')).toHaveTextContent('Every client has something in it.');
    unmount();
    authFetch.mockResolvedValue(reply({}, false));
    render(<ClientCleanup />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The API answered 500');
  });
});
