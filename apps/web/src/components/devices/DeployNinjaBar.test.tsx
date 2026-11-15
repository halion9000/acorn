import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ deployOptions: vi.fn(), deployNinja: vi.fn(), consoleLine: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), devicesApi: api }));

import DeployNinjaBar, { planBulk } from './DeployNinjaBar';

const options = (id: string, device: string, over: Record<string, unknown> = {}) => ({
  device_id: id,
  device,
  blocked: null,
  suggested_package: 'msi',
  roles: [
    { id: 202, name: 'WINDOWS_LAPTOP', node_class: 'WINDOWS_WORKSTATION' },
    { id: 206, name: 'MAC_LAPTOP', node_class: 'MAC' },
  ],
  organizations: [{ id: 27, name: 'Acme Dental', locations: [{ id: 27, name: 'Main' }] }],
  suggested_org_id: 27,
  ...over,
});
const line = (over: Record<string, unknown> = {}) => ({ request_id: 'r1', command: 'Install', status: 'pending', output: null, requested_at: '2026-11-14T10:00:00Z', finished_at: null, ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.deployOptions.mockImplementation(async (id: string) =>
    id === 'a' ? options('a', 'PC-A') : id === 'b' ? options('b', 'MAC-B', { suggested_package: 'pkg' }) : options('c', 'PC-C', { blocked: 'NinjaOne already knows this machine.' }),
  );
  api.deployNinja.mockImplementation(async (id: string) => line({ request_id: `r-${id}` }));
});

describe('planBulk', () => {
  it('gives each machine its own package and leaves out the blocked ones and the ones the role does not fit', () => {
    const each = [options('a', 'PC-A'), options('b', 'MAC-B', { suggested_package: 'pkg' }), options('c', 'PC-C', { blocked: 'already in NinjaOne' })] as never;
    expect(planBulk(each, null).map((p) => [p.device, p.package])).toEqual([['PC-A', 'msi'], ['MAC-B', 'pkg'], ['PC-C', null]]);
    const fitted = planBulk(each, 'WINDOWS_WORKSTATION');
    expect(fitted.map((p) => p.package)).toEqual(['msi', null, null]);
    expect(fitted[1]!.skip).toMatch(/not a Mac role/);
    expect(fitted[2]!.skip).toBe('already in NinjaOne');
  });
});

describe('DeployNinjaBar', () => {
  it('shows nothing when no machine is ticked', () => {
    const { container } = render(<DeployNinjaBar deviceIds={[]} onClear={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('lists what each machine would get, installs only the ones that fit after one confirmation, and shows each result', async () => {
    render(<DeployNinjaBar deviceIds={['a', 'b', 'c']} onClear={() => undefined} />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne to these machines' }));
    const planBox = await screen.findByTestId('bulk-plan');
    expect(planBox).toHaveTextContent('PC-A: Windows installer');
    expect(planBox).toHaveTextContent('MAC-B: Mac package');
    expect(planBox).toHaveTextContent('PC-C: left out, NinjaOne already knows this machine.');
    await userEvent.selectOptions(screen.getByLabelText('Role'), '202');
    expect(planBox).toHaveTextContent('MAC-B: left out, the chosen role is not a Mac role');
    await userEvent.click(screen.getByRole('button', { name: 'Install NinjaOne on 1 machine' }));
    expect(api.deployNinja).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Yes, install' }));
    await waitFor(() => expect(api.deployNinja).toHaveBeenCalledTimes(1));
    expect(api.deployNinja).toHaveBeenCalledWith('a', { package: 'msi', org_id: 27, location_id: 27, role_id: 202 });
    expect(await screen.findByTestId('bulk-results')).toHaveTextContent('PC-A: installing and waiting');
  });

  it('a machine whose request is refused says why and the others still go', async () => {
    api.deployNinja.mockImplementation(async (id: string) => {
      if (id === 'a') throw new Error('No ScreenConnect session');
      return line({ request_id: `r-${id}` });
    });
    api.deployOptions.mockImplementation(async (id: string) => options(id, `PC-${id}`));
    render(<DeployNinjaBar deviceIds={['a', 'b']} onClear={() => undefined} />);
    await userEvent.click(screen.getByRole('button', { name: 'Deploy NinjaOne to these machines' }));
    await screen.findByTestId('bulk-plan');
    await userEvent.selectOptions(screen.getByLabelText('Role'), '202');
    await userEvent.click(screen.getByRole('button', { name: 'Install NinjaOne on 2 machines' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, install' }));
    const results = await screen.findByTestId('bulk-results');
    expect(within(results).getByText(/PC-a: No ScreenConnect session/)).toBeTruthy();
    expect(within(results).getByText(/PC-b: installing/)).toBeTruthy();
    expect(api.deployNinja).toHaveBeenCalledTimes(2);
  });
});
