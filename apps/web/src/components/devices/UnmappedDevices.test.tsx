import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ unmapped: vi.fn() }));
vi.mock('@/lib/api', () => ({ devicesApi: api }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock('@/components/mssp/VendorBadge', () => ({ default: ({ vendor }: { vendor: string }) => <span data-testid="badge">{vendor}</span> }));
vi.mock('@/components/mssp/ClientMapping', () => ({ vendorLabel: (v: string) => `Tool ${v}` }));

import UnmappedDevices from './UnmappedDevices';

const group = (over: Record<string, unknown> = {}) => ({ vendor: 'ninjaone', vendor_client_id: '7', name: 'Acme Dental', devices: 8, hostnames: ['PC-1', 'PC-2', 'PC-3', 'PC-4', 'PC-5', 'PC-6', 'PC-7', 'PC-8'], ...over });

const view = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <UnmappedDevices />
    </SWRConfig>,
  );

beforeEach(() => {
  api.unmapped.mockReset();
});
afterEach(() => cleanup());

describe('UnmappedDevices', () => {
  it('shows nothing at all when nothing is waiting', async () => {
    api.unmapped.mockResolvedValue([]);
    const { container } = view();
    await waitFor(() => expect(api.unmapped).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('says a failed read failed, instead of looking like nothing is waiting', async () => {
    api.unmapped.mockRejectedValue(new Error('API 500'));
    view();
    expect(await screen.findByTestId('unmapped-error')).toHaveTextContent('Could not check for devices waiting for a client: API 500.');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByTestId('unmapped-devices')).toBeNull();
  });

  it('counts the devices in the heading, opens to a table with scoped headers, and links to map the clients', async () => {
    api.unmapped.mockResolvedValue([group(), group({ vendor: 'huntress', vendor_client_id: '9', name: null, devices: 2, hostnames: ['SRV-1', 'SRV-2'] })]);
    view();
    const panel = await screen.findByTestId('unmapped-devices');
    expect(panel).toHaveTextContent('Waiting for a client (10)');
    expect(screen.queryByRole('table')).toBeNull();
    await userEvent.click(within(panel).getByRole('button', { expanded: false }));
    const table = screen.getByRole('table');
    const headers = within(table).getAllByRole('columnheader');
    expect(headers).toHaveLength(5);
    expect(headers.every((h) => h.getAttribute('scope') === 'col')).toBe(true);
    const rows = screen.getAllByTestId('unmapped-group');
    expect(rows[0]).toHaveTextContent('Acme Dental');
    expect(rows[1]).toHaveTextContent('9');
    expect(within(rows[0]).getByRole('link', { name: 'Map clients' })).toHaveAttribute('href', '/mssp?vendor=ninjaone');
  });

  it('shows the first five machines and the rest on request', async () => {
    api.unmapped.mockResolvedValue([group()]);
    view();
    await userEvent.click(await screen.findByRole('button', { expanded: false }));
    const row = screen.getByTestId('unmapped-group');
    expect(row).toHaveTextContent('PC-1, PC-2, PC-3, PC-4, PC-5');
    expect(row).not.toHaveTextContent('PC-6');
    await userEvent.click(within(row).getByRole('button', { name: 'show all 8' }));
    expect(row).toHaveTextContent('PC-8');
    await userEvent.click(within(row).getByRole('button', { name: 'show fewer' }));
    expect(row).not.toHaveTextContent('PC-6');
  });
});
