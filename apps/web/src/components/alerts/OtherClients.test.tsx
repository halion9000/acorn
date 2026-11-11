import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ otherClients: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { otherClients: api.otherClients } }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

import { OtherClients, otherClientsText } from './OtherClients';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><OtherClients alertId="a1" /></SWRConfig>);

beforeEach(() => {
  api.otherClients.mockReset();
});

describe('otherClientsText', () => {
  it('counts clients and alerts, in the singular for one', () => {
    expect(otherClientsText({ window_hours: 24, total: 5, client_count: 3, clients: [] })).toBe('The same alert was raised at 3 other clients in the last 24 hours (5 alerts). It may be one campaign.');
    expect(otherClientsText({ window_hours: 24, total: 1, client_count: 1, clients: [] })).toBe('The same alert was raised at 1 other client in the last 24 hours (1 alert). It may be one campaign.');
  });
});

describe('OtherClients', () => {
  it('lists each client with its count and a link to its newest alert, and counts the clients it does not list', async () => {
    api.otherClients.mockResolvedValue({
      window_hours: 24,
      total: 9,
      client_count: 4,
      clients: [
        { client_id: 'b', name: 'Birch', count: 2, newest_at: '2026-11-11T10:30:00+00:00', newest_alert_id: 'b9' },
        { client_id: 'c', name: 'Cedar', count: 1, newest_at: null, newest_alert_id: null },
      ],
    });
    show();
    const card = await screen.findByTestId('other-clients');
    expect(card).toHaveTextContent('4 other clients in the last 24 hours (9 alerts)');
    const rows = screen.getAllByTestId('other-client');
    expect(rows[0]).toHaveTextContent('Birch: 2, newest 2026-11-11 10:30 UTC');
    expect(screen.getByRole('link', { name: 'Birch' })).toHaveAttribute('href', '/alerts/b9');
    expect(rows[1]).toHaveTextContent('Cedar: 1');
    expect(screen.queryByRole('link', { name: 'Cedar' })).toBeNull();
    expect(screen.getByTestId('other-client-more')).toHaveTextContent('and 2 more');
    expect(api.otherClients).toHaveBeenCalledWith('a1');
  });

  it('shows nothing when no other client has it', async () => {
    api.otherClients.mockResolvedValue({ window_hours: 24, total: 0, client_count: 0, clients: [] });
    show();
    await waitFor(() => expect(api.otherClients).toHaveBeenCalled());
    expect(screen.queryByTestId('other-clients')).toBeNull();
  });

  it('shows nothing when it cannot be read', async () => {
    api.otherClients.mockRejectedValue(new Error('no'));
    show();
    await waitFor(() => expect(api.otherClients).toHaveBeenCalled());
    expect(screen.queryByTestId('other-clients')).toBeNull();
  });
});
