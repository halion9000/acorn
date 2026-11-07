import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ get: vi.fn(), children: vi.fn() }));
vi.mock('@/lib/api', () => ({ environmentApi: { get: api.get }, msspApi: { listChildren: api.children } }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('client=c1') }));
vi.mock('next/link', () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import ClientEnvironmentView from './ClientEnvironmentView';

const env = (over: Record<string, unknown> = {}) => ({
  client_id: 'c1',
  client_name: 'Airport Security Park',
  counts: { network: 1, computer: 1, camera: 0, other: 0 },
  tools: { auvik: 1, ninjaone: 1 },
  gaps: { huntress: 1 },
  has_auvik: true,
  has_links: true,
  truncated: false,
  devices: [
    { id: 'd1', hostname: 'fw-1', kind: 'network', role: 'firewall', online: true, tools: ['auvik'], links: [{ name: 'core-switch', port: 'LAN', remote_port: 'Gi1/0/1', speed: '1 Gbps' }], missing: [] },
    { id: 'd2', hostname: 'pc-1', kind: 'computer', role: null, online: true, tools: ['ninjaone'], links: [], missing: ['huntress'] },
  ],
  ...over,
});

beforeEach(() => {
  api.children.mockReset().mockResolvedValue([{ id: 'c1', name: 'Airport Security Park', mssp_role: 'client' }]);
  api.get.mockReset().mockResolvedValue(env());
});

describe('ClientEnvironmentView', () => {
  it('opens the client named in the address and shows counts, gaps, each device and what it is plugged into', async () => {
    render(<ClientEnvironmentView />);
    expect(await screen.findByText('fw-1')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('c1');
    expect(screen.getByText(/LAN → core-switch \(Gi1\/0\/1\) · 1 Gbps/)).toBeInTheDocument();
    expect(screen.getByTestId('env-gaps')).toHaveTextContent('Huntress 1');
    expect(screen.getByText('Missing: Huntress')).toBeInTheDocument();
  });

  it('says there is no wiring to show when Auvik has not reported the client, or has reported no links', async () => {
    api.get.mockResolvedValueOnce(env({ has_auvik: false, has_links: false }));
    const a = render(<ClientEnvironmentView />);
    expect(await screen.findByText(/Auvik has not reported this client/)).toBeInTheDocument();
    a.unmount();
    api.get.mockResolvedValueOnce(env({ has_links: false }));
    render(<ClientEnvironmentView />);
    expect(await screen.findByText(/has not named what any device is plugged into/)).toBeInTheDocument();
  });

  it('shows why a client could not be loaded, and loads another when one is chosen', async () => {
    api.get.mockRejectedValueOnce(new Error('No such client'));
    render(<ClientEnvironmentView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No such client');
    api.children.mockResolvedValue([{ id: 'c1', name: 'Airport Security Park', mssp_role: 'client' }, { id: 'c2', name: 'Other', mssp_role: 'client' }]);
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Client' }), 'c1');
    await waitFor(() => expect(api.get).toHaveBeenCalled());
  });
});
