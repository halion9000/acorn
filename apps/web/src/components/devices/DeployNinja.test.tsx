import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ deployOptions: vi.fn(), deployNinja: vi.fn(), consoleLine: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), devicesApi: api }));

import { DeployNinja, rolesFor } from './DeployNinja';

const options = (over: Record<string, unknown> = {}) => ({
  device_id: 'd1',
  device: 'PC-1',
  blocked: null,
  suggested_package: 'msi',
  roles: [
    { id: 202, name: 'WINDOWS_LAPTOP', node_class: 'WINDOWS_WORKSTATION' },
    { id: 1004, name: 'Windows Server (2016 or above)', node_class: 'WINDOWS_SERVER' },
    { id: 206, name: 'MAC_LAPTOP', node_class: 'MAC' },
  ],
  organizations: [
    { id: 22, name: 'Beta Law', locations: [{ id: 22, name: 'Main' }] },
    { id: 27, name: 'Acme Dental', locations: [{ id: 28, name: 'Annex' }, { id: 27, name: 'Main' }] },
  ],
  suggested_org_id: 27,
  ...over,
});
const line = (over: Record<string, unknown> = {}) => ({ request_id: 'r1', command: 'Install the NinjaOne agent', status: 'pending', output: null, requested_at: '2026-11-14T10:00:00Z', finished_at: null, ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.deployOptions.mockResolvedValue(options());
});

describe('rolesFor', () => {
  it('offers Windows roles for an MSI and Mac roles for a PKG', () => {
    const o = options() as never;
    expect(rolesFor(o, 'msi').map((r) => r.id)).toEqual([202, 1004]);
    expect(rolesFor(o, 'pkg').map((r) => r.id)).toEqual([206]);
  });
});

describe('DeployNinja', () => {
  it('opens with the client mapped organization chosen, and offers only the roles that fit the package', async () => {
    render(<DeployNinja deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne' }));
    const org = (await screen.findByLabelText('Organization')) as HTMLSelectElement;
    await waitFor(() => expect(org.value).toBe('27'));
    expect(Array.from((screen.getByLabelText('Location') as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(['Annex', 'Main']);
    expect(Array.from((screen.getByLabelText('Role') as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(['Choose a role', 'WINDOWS_LAPTOP', 'Windows Server (2016 or above)']);
    await userEvent.selectOptions(screen.getByLabelText('Package'), 'pkg');
    expect(Array.from((screen.getByLabelText('Role') as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(['Choose a role', 'MAC_LAPTOP']);
  });

  it('asks for a confirmation, then queues the install with the chosen values and shows the answer when it comes', async () => {
    api.deployNinja.mockResolvedValue(line());
    render(<DeployNinja deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne' }));
    await screen.findByLabelText('Role');
    expect((screen.getByRole('button', { name: 'Install NinjaOne' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('Role'), '202');
    await userEvent.click(screen.getByRole('button', { name: 'Install NinjaOne' }));
    expect(api.deployNinja).not.toHaveBeenCalled();
    expect(screen.getByText(/Install the agent on PC-1 as SYSTEM, for Acme Dental\?/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, install' }));
    expect(api.deployNinja).toHaveBeenCalledWith('d1', { package: 'msi', org_id: 27, location_id: 28, role_id: 202 });
    expect(await screen.findByText(/waiting for the machine to enroll/)).toBeTruthy();
    api.consoleLine.mockResolvedValue(line({ status: 'done', output: 'NinjaOne agent installed on PC-1, enrolled in Acme Dental, and its role set to WINDOWS_LAPTOP.' }));
    await waitFor(() => expect(screen.getByTestId('deploy-result')).toHaveTextContent('its role set to WINDOWS_LAPTOP'), { timeout: 6000 });
  });

  it('says why when nothing can be deployed, and offers no install button', async () => {
    api.deployOptions.mockResolvedValue(options({ blocked: 'NinjaOne already has this machine.' }));
    render(<DeployNinja deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne' }));
    expect(await screen.findByText('NinjaOne already has this machine.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Install NinjaOne' })).toBeNull();
  });

  it('shows the reason when the API refuses the request, and a failed result in red text', async () => {
    api.deployNinja.mockRejectedValue(new Error('Something for this machine is still waiting for an answer.'));
    render(<DeployNinja deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne' }));
    await screen.findByLabelText('Role');
    await userEvent.selectOptions(screen.getByLabelText('Role'), '202');
    await userEvent.click(screen.getByRole('button', { name: 'Install NinjaOne' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, install' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('still waiting for an answer');
  });
});
