import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ mdmClients: vi.fn(), setMdmClients: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: api, apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null) }));

import { MdmElsewhere, filterClients } from './MdmElsewhere';

const clients = [
  { client_id: 'c1', client_name: 'Acme Dental', elsewhere: true, hidden_alerts: 3 },
  { client_id: 'c2', client_name: 'Birch Law', elsewhere: false, hidden_alerts: 0 },
];

beforeEach(() => {
  api.mdmClients.mockReset();
  api.setMdmClients.mockReset();
  api.mdmClients.mockResolvedValue({ clients });
});

describe('filterClients', () => {
  it('finds a client in any case', () => {
    expect(filterClients(clients, 'BIRCH').map((c) => c.client_name)).toEqual(['Birch Law']);
    expect(filterClients(clients, '  ')).toBe(clients);
  });
});

describe('MdmElsewhere', () => {
  it('shows the clients with the ones marked ticked and how many alerts are hidden, and saves only when something changed', async () => {
    api.setMdmClients.mockResolvedValue({ clients: [{ ...clients[0], elsewhere: true }, { ...clients[1], elsewhere: true, hidden_alerts: 2 }] });
    render(<MdmElsewhere />);
    expect(((await screen.findByLabelText('Acme Dental')) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('(3 hidden now)')).toBeTruthy();
    const save = screen.getByRole('button', { name: 'Save' });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByLabelText('Birch Law'));
    expect((save as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(save);
    await waitFor(() => expect(api.setMdmClients).toHaveBeenCalledWith(expect.arrayContaining(['c1', 'c2'])));
    expect(api.setMdmClients.mock.calls[0]![0]).toHaveLength(2);
    expect(await screen.findByText('Saved: 2 clients with their MDM managed elsewhere.')).toBeTruthy();
  });

  it('shows nothing when there are no clients or the read fails', async () => {
    api.mdmClients.mockResolvedValue({ clients: [] });
    const { container, unmount } = render(<MdmElsewhere />);
    await waitFor(() => expect(api.mdmClients).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="mdm-elsewhere"]')).toBeNull();
    unmount();
    api.mdmClients.mockRejectedValue(new Error('no'));
    const second = render(<MdmElsewhere />);
    await waitFor(() => expect(api.mdmClients).toHaveBeenCalledTimes(2));
    expect(second.container.querySelector('[data-testid="mdm-elsewhere"]')).toBeNull();
  });
});
