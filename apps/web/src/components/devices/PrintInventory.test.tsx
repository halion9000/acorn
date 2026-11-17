import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const list = vi.hoisted(() => vi.fn());
let query = 'client=c1';
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(query) }));
vi.mock('@/lib/api', () => ({ devicesApi: { list } }));

import PrintInventory from './PrintInventory';

const dev = (hostname: string, over: Record<string, unknown> = {}) => ({ id: hostname, client_name: 'Acme Dental', hostname, serial_number: 'SN-' + hostname, os: 'Windows 11', os_version: null, manufacturer: 'Dell', model: 'X', ip_addresses: [], last_seen: '', first_seen: '', sources: [], in_master: true, kind: 'computer', ...over });

describe('the printable inventory', () => {
  beforeEach(() => {
    list.mockReset();
    query = 'client=c1';
  });

  it('reads every page of the client\u2019s devices and lists them by name with the counts by kind', async () => {
    list.mockImplementation(async ({ page }: { page: number }) => (page === 1 ? { items: [dev('zeta'), dev('Alpha')], pages: 2 } : { items: [dev('sw', { kind: 'network' })], pages: 2 }));
    render(<PrintInventory today="2026-11-16" />);
    const table = await screen.findByTestId('inventory-table');
    expect([...table.querySelectorAll('tbody tr')].map((r) => r.querySelector('td')?.textContent)).toEqual(['Alpha', 'sw', 'zeta']);
    expect(screen.getByRole('heading')).toHaveTextContent('Acme Dental: device inventory');
    expect(screen.getByText(/2026-11-16 · 3 devices \(2 computers, 1 network device\)/)).toBeInTheDocument();
    expect(list.mock.calls.map((c) => [c[0].clientId, c[0].page, c[0].pageSize])).toEqual([['c1', 1, 200], ['c1', 2, 200]]);
  });

  it('asks to choose a client when none is given, says when there are no devices, and says why when the load fails', async () => {
    query = '';
    const first = render(<PrintInventory />);
    expect(screen.getByText(/Choose a client on the Devices page/)).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
    first.unmount();
    query = 'client=c1';
    list.mockResolvedValue({ items: [], pages: 1 });
    const second = render(<PrintInventory />);
    expect(await screen.findByText('This client has no devices on record.')).toBeInTheDocument();
    second.unmount();
    list.mockRejectedValue(new Error('API 500'));
    render(<PrintInventory />);
    expect(await screen.findByRole('alert')).toHaveTextContent('API 500');
  });
});
