import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { DeviceList, DeviceRow } from '@/lib/api';

const listMock = vi.fn();
vi.mock('@/lib/api', () => ({
  devicesApi: { rollup: async () => [], merges: async () => [], list: (...a: unknown[]) => listMock(...a), exportCsv: vi.fn(), setMaster: vi.fn(), hide: vi.fn(), unhide: vi.fn(), duplicates: async () => ({ items: [] }) },
  msspApi: { listChildren: async () => [] },
  apiErrorDetail: () => null,
}));
const routerParams = vi.hoisted(() => ({ current: new URLSearchParams('') }));
vi.mock('next/navigation', () => ({ useSearchParams: () => routerParams.current }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import DevicesView, { filtersFromParams, filtersToParams, withFilterParams } from './DevicesView';

const NOW = '2026-10-15T15:00:00Z';
const row = (hostname: string): DeviceRow => ({
  id: `d-${hostname}`, tenant_id: 't1', client_name: 'Acme', hostname, serial_number: null, os: 'Windows 11', os_version: null, manufacturer: null, model: null,
  ip_addresses: [], last_seen: NOW, first_seen: NOW, sources: [{ vendor: 'ninjaone', name: hostname, last_seen: NOW }], in_master: true, kind: 'computer',
});
const answer = (items: DeviceRow[]): DeviceList => ({ master_vendor: null, summary: { total: 10, not_in_master: 0, kinds: { computer: 6, network: 3, camera: 1, other: 0 } }, items, total: items.length, page: 1, page_size: 50 } as unknown as DeviceList);

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, '', '/devices');
  routerParams.current = new URLSearchParams('');
  listMock.mockReset().mockImplementation(async () => answer([row('PC-1')]));
});

describe('the filters in the address', () => {
  it('writes every filter that is set and nothing else, and reading it back gives the same filters', () => {
    const all = { clientId: 'c-1', vendor: 'huntress', os: 'mac', kind: 'network', missing: 'huntress' as const, attentionOnly: true, staleOnly: true, followedOnly: true, notEncryptedOnly: true, mdm: 'not_ade' as const, offlineOnly: true, alertsOnly: true, presence: 'all' as const };
    const params = filtersToParams(all);
    expect(params.toString()).toBe('client=c-1&tool=huntress&os=mac&kind=network&missing=huntress&attention=1&stale=1&followed=1&encryption=not_encrypted&mdm=not_ade&offline=1&alerts=1&show=all');
    expect(filtersFromParams(params)).toEqual(all);
    expect(filtersToParams({ clientId: '', vendor: '', gapsOnly: false, alertsOnly: false }).toString()).toBe('');
  });

  it('replaces the filters in an address and leaves anything else, such as a search, alone', () => {
    expect(withFilterParams('search=PC-1&client=old&stale=1', { clientId: 'new', offlineOnly: true })).toBe('search=PC-1&client=new&offline=1');
    expect(withFilterParams('search=PC-1&client=old', {})).toBe('search=PC-1');
    expect(withFilterParams('', { os: 'windows' })).toBe('os=windows');
  });
});

describe('the page and its address', () => {
  it('puts a filter the person picks into the address, and takes it out again', async () => {
    render(<DevicesView />);
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByRole('tab', { name: /Cameras/ }));
    await waitFor(() => expect(window.location.search).toBe('?kind=camera'));
    await userEvent.click(screen.getByRole('tab', { name: /All devices/ }));
    await waitFor(() => expect(window.location.search).toBe(''));
  });

  it('keeps the search a link carried when it writes the filters', async () => {
    window.history.replaceState(null, '', '/devices?search=PC-1');
    routerParams.current = new URLSearchParams('search=PC-1');
    render(<DevicesView />);
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByRole('tab', { name: /Cameras/ }));
    await waitFor(() => expect(window.location.search).toContain('kind=camera'));
    expect(window.location.search).toContain('search=PC-1');
  });
});
