import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';
import type { DeviceList } from '@/lib/api';

const listMock = vi.fn();
const viewsMock = vi.fn();
vi.mock('@/lib/api', () => ({
  devicesApi: { unmapped: async () => [], rollup: async () => [], merges: async () => [], list: (...a: unknown[]) => listMock(...a), setMaster: async () => ({}), hide: async () => ({}), unhide: async () => ({}), duplicates: async () => ({ items: [] }) },
  msspApi: { listChildren: async () => [{ id: 'c1', name: 'Acme', mssp_role: 'child' }] },
  savedViewsApi: { list: (t: string) => viewsMock(t), create: async () => ({}), update: async () => ({}), delete: async () => undefined },
  apiErrorDetail: () => null,
  ApiError: class ApiError extends Error {},
}));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('') }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import DevicesView from './DevicesView';

const empty: DeviceList = { master_vendor: null, summary: { total: 0, not_in_master: 0 }, items: [], total: 0, page: 1, page_size: 50, pages: 1 };
const view = (id: string, name: string, filters: Record<string, unknown>) => ({ id, view_type: 'devices', name, filters, columns: null, is_default: false, created_at: '2026-11-02T00:00:00Z', updated_at: '2026-11-02T00:00:00Z' });

function renderDevices() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DevicesView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  listMock.mockReset().mockResolvedValue(empty);
  viewsMock.mockReset().mockResolvedValue([view('v1', 'Old Macs', { staleOnly: true, os: 'mac' }), view('v2', 'Everything', {})]);
});

describe('Devices > saved views', () => {
  it('asks for the devices views and shows them above the filters', async () => {
    renderDevices();
    expect(await screen.findByRole('button', { name: /^Old Macs$/ })).toBeInTheDocument();
    expect(viewsMock).toHaveBeenCalledWith('devices');
  });

  it('clicking a saved view puts its filters on the page, and a view with none clears them', async () => {
    renderDevices();
    const stale = await screen.findByRole('button', { name: /Stale agents/ });
    expect(stale).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(await screen.findByRole('button', { name: /^Old Macs$/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Stale agents/ })).toHaveAttribute('aria-pressed', 'true'));
    await waitFor(() => expect(JSON.stringify(listMock.mock.calls.at(-1))).toMatch(/mac/));
    await userEvent.click(screen.getByRole('button', { name: /^Everything$/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Stale agents/ })).toHaveAttribute('aria-pressed', 'false'));
  });
});
