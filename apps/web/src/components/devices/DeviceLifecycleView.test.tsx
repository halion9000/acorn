import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren: async () => [] } }));

import { DeviceLifecycleView, ageText } from './DeviceLifecycleView';

const row = (over: Record<string, unknown>) => ({ device_id: 'd', client_name: 'Acme', hostname: 'PC-1', os: 'Windows 11 Pro', manufacturer: 'Dell', model: 'Latitude', serial_number: 'S', first_seen: '2026-08-01T00:00:00+00:00', age_days: 100, band: 'under_1', os_support: 'supported', review: false, ...over });
const body = {
  basis: 'first_seen',
  summary: { computers: 3, bands: { under_1: 1, '1_to_3': 0, '3_to_5': 0, over_5: 2 }, os_ended: 1, os_unknown: 0, review: 2 },
  rows: [row({ device_id: 'a', hostname: 'OLD-WIN10', os: 'Windows 10 Pro', os_support: 'ended', review: true, age_days: 800, band: '1_to_3' }), row({ device_id: 'b', hostname: 'ANCIENT', age_days: 2300, band: 'over_5', review: true }), row({ device_id: 'c', hostname: 'NEW-PC' })],
};

afterEach(() => {
  cleanup();
  authFetch.mockReset();
});

describe('device lifecycle', () => {
  it('says age is counted from first seen, lists worst first with the OS support, and can show only the machines worth a review', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(body) });
    render(<DeviceLifecycleView />);
    expect(screen.getByText(/first saw/)).toBeInTheDocument();
    const table = await screen.findByTestId('lifecycle-table');
    expect(within(table).getAllByTestId('lifecycle-row').map((r) => r.textContent)).toEqual([expect.stringContaining('OLD-WIN10'), expect.stringContaining('ANCIENT'), expect.stringContaining('NEW-PC')]);
    expect(within(table).getByText('Ended')).toBeInTheDocument();
    expect(screen.getByTestId('lifecycle-summary')).toHaveTextContent('Operating system ended1');
    await userEvent.click(screen.getByRole('checkbox'));
    expect(within(table).getAllByTestId('lifecycle-row')).toHaveLength(2);
  });

  it('writes ages in days, months or years and says when the permission is missing', async () => {
    expect([ageText(10), ageText(100), ageText(800)]).toEqual(['10 days', '3 months', '2.2 years']);
    authFetch.mockResolvedValue({ ok: false, status: 403, json: () => Promise.resolve({}) });
    render(<DeviceLifecycleView />);
    expect(await screen.findByText(/needs the alerts permission/)).toBeInTheDocument();
  });
});
