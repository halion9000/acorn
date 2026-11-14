import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { DeviceList, DeviceRow } from '@/lib/api';

const listMock = vi.fn();
const exportMock = vi.fn();
vi.mock('@/lib/api', () => ({
  devicesApi: { rollup: async () => [], merges: async () => [], list: (...a: unknown[]) => listMock(...a), exportCsv: (...a: unknown[]) => exportMock(...a), setMaster: vi.fn(), hide: vi.fn(), unhide: vi.fn(), duplicates: async () => ({ items: [] }) },
  msspApi: { listChildren: async () => [] },
  apiErrorDetail: () => null,
}));
const routerParams = vi.hoisted(() => ({ current: new URLSearchParams('') }));
vi.mock('next/navigation', () => ({ useSearchParams: () => routerParams.current }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import DevicesView from './DevicesView';

const NOW = '2026-10-15T15:00:00Z';
const row = (hostname: string, kind: DeviceRow['kind'] = 'computer'): DeviceRow => ({
  id: `d-${hostname}`, tenant_id: 't1', client_name: 'Acme', hostname, serial_number: null, os: 'Windows 11', os_version: null, manufacturer: null, model: null,
  ip_addresses: [], last_seen: NOW, first_seen: NOW, sources: [{ vendor: 'ninjaone', name: hostname, last_seen: NOW }], in_master: true, kind,
});
const answer = (items: DeviceRow[], kinds: DeviceList['summary']['kinds']): DeviceList => ({ master_vendor: null, summary: { total: 10, not_in_master: 0, kinds }, items, total: items.length, page: 1, page_size: 50, pages: 1 });

beforeEach(() => {
  window.localStorage.clear();
  routerParams.current = new URLSearchParams('');
  listMock.mockReset().mockImplementation(async (q: { kind?: string }) => answer(q.kind === 'network' ? [row('SW-1', 'network')] : q.kind === 'camera' ? [row('CAM-1', 'camera')] : [row('PC-1')], { computer: 6, network: 3, camera: 1, other: 0 }));
  exportMock.mockReset().mockResolvedValue('csv');
});

describe('the online / offline / all choice', () => {
  it('starts on online, and every list request and export says so', async () => {
    render(<DevicesView />);
    await screen.findByText('PC-1');
    const toggle = screen.getByTestId('presence-toggle');
    expect(toggle.querySelector('[aria-pressed="true"]')).toHaveTextContent('online');
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ presence: 'online' }));
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(exportMock).toHaveBeenCalledWith(expect.objectContaining({ presence: 'online' })));
  });

  it('offline and all are asked for when picked, back on page 1, and the pick is remembered for next time', async () => {
    const { unmount } = render(<DevicesView />);
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByRole('button', { name: 'offline' }));
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ presence: 'offline', page: 1 })));
    await userEvent.click(screen.getByRole('button', { name: 'all' }));
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ presence: 'all' })));
    unmount();
    render(<DevicesView />);
    await screen.findByText('PC-1');
    expect(screen.getByTestId('presence-toggle').querySelector('[aria-pressed="true"]')).toHaveTextContent('all');
  });

  it('a link that names a problem filter (a tile) lists all machines until the person picks, so the list matches the tile count', async () => {
    routerParams.current = new URLSearchParams('missing=huntress');
    render(<DevicesView />);
    await screen.findByText('PC-1');
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ missing: 'huntress', presence: 'all' }));
    expect(screen.getByTestId('presence-toggle').querySelector('[aria-pressed="true"]')).toHaveTextContent('all');
    await userEvent.click(screen.getByRole('button', { name: 'online' }));
    await waitFor(() => expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ missing: 'huntress', presence: 'online' })));
  });
});
