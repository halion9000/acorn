import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DeviceVersions, behindText } from './DeviceVersions';

const ok = (b: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => b });
const HUNTRESS = {
  newest: '0.14.10', agents: 5, without_version: 1,
  spread: [{ version: '0.14.10', agents: 3, releases_behind: 0 }, { version: '0.13.0', agents: 2, releases_behind: 4 }],
  old: [{ client: 'Birch Law', hostname: 'PC-2', version: '0.13.0', releases_behind: 4, last_callback: null }, { client: 'Acme Dental', hostname: 'PC-1', version: '0.13.0', releases_behind: 4, last_callback: '2026-11-17' }],
};
const FIRMWARE = {
  models: [{ manufacturer: 'Cisco', model: 'C9200', newest: '17.12.1', devices: 4, behind: 2, versions: ['17.12.1', '17.9.4'] }],
  devices: [{ client: 'Acme Dental', hostname: 'sw1', manufacturer: 'Cisco', model: 'C9200', device_type: 'switch', firmware: '17.9.4', newest: '17.12.1' }],
};

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => ok(url.includes('huntress') ? HUNTRESS : FIRMWARE));
});

describe('behindText', () => {
  it('says current, one release or several behind', () => {
    expect([behindText(0), behindText(1), behindText(4)]).toEqual(['Current', '1 release behind', '4 releases behind']);
  });
});

describe('DeviceVersions', () => {
  it('summarizes the Huntress agents, lists those more than two releases behind and sorts a column', async () => {
    render(<DeviceVersions />);
    const section = await screen.findByTestId('huntress-versions');
    expect(await within(section).findByText(/5 agents; newest version/)).toBeTruthy();
    const old = await within(section).findByTestId('huntress-old');
    const clients = () => within(old).getAllByRole('row').slice(1).map((r) => r.querySelector('td')!.textContent);
    expect(clients()).toEqual(['Birch Law', 'Acme Dental']);
    await userEvent.click(within(old).getByRole('button', { name: /Client/ }));
    expect(clients()).toEqual(['Acme Dental', 'Birch Law']);
  });

  it('lists the network devices behind with the newest firmware of their make and model', async () => {
    render(<DeviceVersions />);
    const devices = await screen.findByTestId('firmware-devices');
    expect(within(devices).getByText('17.9.4')).toBeTruthy();
    expect(within(devices).getByText('17.12.1')).toBeTruthy();
    expect(within(await screen.findByTestId('firmware-models')).getByText('17.12.1, 17.9.4')).toBeTruthy();
  });

  it('says so when nothing is behind or no agent has a version, and shows a failed read', async () => {
    authFetch.mockImplementation((url: string) => (url.includes('huntress') ? ok({ newest: null, agents: 0, without_version: 0, spread: [], old: [] }) : Promise.resolve({ ok: false, status: 500, json: async () => ({}) })));
    render(<DeviceVersions />);
    expect(await screen.findByText('No Huntress agent has reported a version yet.')).toBeTruthy();
    expect(await screen.findByText('The API answered 500')).toBeTruthy();
  });
});
