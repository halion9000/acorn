import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';
import type { DeviceList, DeviceRow } from '@/lib/api';

const listMock = vi.fn();
vi.mock('@/lib/api', () => ({
  devicesApi: { unmapped: async () => [], rollup: async () => [], merges: async () => [], list: (...a: unknown[]) => listMock(...a), setMaster: vi.fn(), hide: vi.fn(), unhide: vi.fn(), duplicates: async () => ({ items: [] }), exportCsv: vi.fn() },
  msspApi: { listChildren: async () => [{ id: 'c1', name: 'Acme', mssp_role: 'child' }, { id: 'c2', name: 'Beta', mssp_role: 'child' }] },
  apiErrorDetail: () => null,
}));
const routerParams = vi.hoisted(() => ({ current: new URLSearchParams('') }));
vi.mock('next/navigation', () => ({ useSearchParams: () => routerParams.current }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import DevicesView from './DevicesView';

const NOW = '2026-10-15T15:00:00Z';
const device = (hostname: string): DeviceRow =>
  ({ id: `d-${hostname}`, hostname, tenant_id: 't1', client_name: 'Acme', serial_number: null, os: 'Windows 11', os_version: null, manufacturer: null, model: null, ip_addresses: [], last_seen: NOW, first_seen: NOW, sources: [{ vendor: 'ninjaone', name: hostname, last_seen: NOW }], in_master: true }) as DeviceRow;
const answer = (hosts: string[]): DeviceList => ({ master_vendor: null, summary: { total: hosts.length, not_in_master: 0 }, items: hosts.map(device), total: hosts.length, page: 1, page_size: 50, pages: 1 }) as DeviceList;

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const view = () => (
  <SWRConfig value={{ provider: () => new Map() }}>
    <DevicesView />
  </SWRConfig>
);

beforeEach(() => {
  window.localStorage.clear();
  listMock.mockReset();
  routerParams.current = new URLSearchParams('');
});

describe('which answer reaches the list', () => {
  it('a slow answer to an earlier filter never replaces the answer to the filter chosen after it', async () => {
    const slow = deferred<DeviceList>();
    listMock.mockImplementation((q: { os?: string }) => (q.os === 'mac' ? Promise.resolve(answer(['MAC-ONLY'])) : slow.promise));
    render(view());
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1)); // the unfiltered first request, still waiting
    await userEvent.selectOptions(await screen.findByLabelText('Operating system'), 'mac');
    expect(await screen.findByText('MAC-ONLY')).toBeInTheDocument();
    await act(async () => {
      slow.resolve(answer(['EVERYTHING-ELSE'])); // the earlier request finally answers
    });
    expect(screen.getByText('MAC-ONLY')).toBeInTheDocument();
    expect(screen.queryByText('EVERYTHING-ELSE')).toBeNull();
  });

  it('a link that names filters loads once, already filtered, not first with none', async () => {
    routerParams.current = new URLSearchParams('client=c1&missing=huntress');
    listMock.mockResolvedValue(answer(['NO-HUNTRESS-1']));
    render(view());
    expect(await screen.findByText('NO-HUNTRESS-1')).toBeInTheDocument();
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(listMock.mock.calls[0][0]).toMatchObject({ clientId: 'c1', missing: 'huntress' });
  });

  it('following a second link while on the page applies that link\'s filters', async () => {
    routerParams.current = new URLSearchParams('client=c1&missing=huntress');
    listMock.mockResolvedValue(answer(['A']));
    const { rerender } = render(view());
    await screen.findByText('A');
    routerParams.current = new URLSearchParams('client=c2&missing=addigy');
    rerender(view());
    await waitFor(() => expect(listMock.mock.calls.at(-1)![0]).toMatchObject({ clientId: 'c2', missing: 'addigy' }));
  });

  it('changing a filter after a link still filters by what was chosen', async () => {
    routerParams.current = new URLSearchParams('client=c1&missing=huntress');
    listMock.mockResolvedValue(answer(['A']));
    render(view());
    await screen.findByText('A');
    await userEvent.selectOptions(await screen.findByLabelText('Operating system'), 'windows');
    await waitFor(() => expect(listMock.mock.calls.at(-1)![0]).toMatchObject({ clientId: 'c1', missing: 'huntress', os: 'windows' }));
  });
});
