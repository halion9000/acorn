import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { DeviceList, DeviceRow } from '@/lib/api';

const listMock = vi.fn();
const optionsMock = vi.fn();
const runMock = vi.fn();
const elsewhereMock = vi.fn();
vi.mock('@/lib/api', () => ({
  devicesApi: {
    unmapped: async () => [],
    rollup: async () => [],
    merges: async () => [],
    list: (...a: unknown[]) => listMock(...a),
    duplicates: async () => ({ items: [] }),
    scriptOptions: () => optionsMock(),
    runScript: (...a: unknown[]) => runMock(...a),
    elsewhere: (...a: unknown[]) => elsewhereMock(...a),
  },
  msspApi: { listChildren: async () => [{ id: 'c1', name: 'Acme', mssp_role: 'child' }] },
  apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null),
}));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('') }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('react-hot-toast', () => ({ default: toast }));

import DevicesView from './DevicesView';
import { deviceRunSummary } from './DeviceScriptBar';
import { matchedText } from './WhereElse';

const NOW = '2026-10-15T15:00:00Z';
const device = (hostname: string): DeviceRow => ({
  id: `d-${hostname}`, hostname, tenant_id: 't1', client_name: 'Acme', serial_number: null, os: 'Windows 11', os_version: null, manufacturer: null, model: null,
  ip_addresses: [], last_seen: NOW, first_seen: NOW, sources: [{ vendor: 'ninjaone', name: hostname, last_seen: NOW }], in_master: true,
});
const list = (items: DeviceRow[]): DeviceList => ({ master_vendor: null, summary: { total: items.length, not_in_master: 0 }, items, total: items.length, page: 1, page_size: 50, pages: 1 });
const plan = (over: Record<string, unknown> = {}) => ({
  batch_id: null, preview: true, script_name: 'Disk Space Scan', runs_at_once: false, queued: 2, skipped: 1,
  items: [
    { device_id: 'd-PC-1', device: 'PC-1', outcome: 'queued', reason: null, request_id: null },
    { device_id: 'd-PC-2', device: 'PC-2', outcome: 'queued', reason: null, request_id: null },
    { device_id: 'd-PC-3', device: 'PC-3', outcome: 'skipped', reason: 'A script request for this machine is already waiting for CORE.', request_id: null },
  ],
  ...over,
});
const renderView = () => render(<DevicesView />);

beforeEach(() => {
  window.localStorage.clear();
  listMock.mockReset().mockResolvedValue(list([device('PC-1'), device('PC-2'), device('PC-3')]));
  optionsMock.mockReset().mockResolvedValue({ scripts: [{ id: 7, name: 'Disk Space Scan', one_click: false }], blocked: null });
  runMock.mockReset();
  toast.success.mockReset();
});

describe('picking devices to run a script on', () => {
  it('says the run in words: machines, a ticket each, one approval, and how many were left out', () => {
    expect(deviceRunSummary(plan() as never)).toBe('"Disk Space Scan" on 2 machines, a new HaloPSA ticket for each. CORE asks you once, for all of them. 1 left out.');
    expect(deviceRunSummary(plan({ queued: 1, skipped: 0, runs_at_once: true }) as never)).toBe('"Disk Space Scan" on 1 machine, a new HaloPSA ticket for each. It is set to run at once in CORE.');
  });

  it('shows no script bar until a device is ticked; ticking a row counts it and clicking the checkbox does not open the row', async () => {
    renderView();
    await screen.findByText('PC-1');
    expect(screen.queryByTestId('device-script-bar')).toBeNull();
    await userEvent.click(screen.getByLabelText('Select PC-1'));
    expect(within(screen.getByTestId('device-script-bar')).getByText('1 selected')).toBeTruthy();
    expect(screen.queryByText('Serial number')).toBeNull(); // the row did not open
    await userEvent.click(screen.getByLabelText('Select PC-1'));
    expect(screen.queryByTestId('device-script-bar')).toBeNull();
  });

  it('the header box ticks every device on the page, and again clears them', async () => {
    renderView();
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByLabelText('Select every device on this page'));
    expect(within(screen.getByTestId('device-script-bar')).getByText('3 selected')).toBeTruthy();
    await userEvent.click(screen.getByLabelText('Select every device on this page'));
    expect(screen.queryByTestId('device-script-bar')).toBeNull();
  });

  it('previews which machines would run, then asks CORE once for the ticked devices and clears the selection', async () => {
    runMock.mockImplementation(async (body: { preview?: boolean }) => (body.preview ? plan() : plan({ preview: false, batch_id: 'abc123', skipped: 0, queued: 3 })));
    renderView();
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByLabelText('Select PC-1'));
    await userEvent.click(screen.getByLabelText('Select PC-2'));
    await userEvent.click(screen.getByRole('button', { name: 'Run script on these machines' }));
    await screen.findByLabelText('Script');
    await userEvent.click(screen.getByRole('button', { name: 'See which machines' }));
    expect(runMock).toHaveBeenLastCalledWith({ script_id: 7, device_ids: ['d-PC-1', 'd-PC-2'], preview: true });
    const shown = await screen.findByTestId('device-script-plan');
    expect(within(shown).getByText(/PC-3 \(A script request for this machine is already waiting for CORE\.\)/)).toBeTruthy();
    await userEvent.click(within(shown).getByRole('button', { name: 'Confirm: run on 2 machines' }));
    await waitFor(() => expect(runMock).toHaveBeenLastCalledWith({ script_id: 7, device_ids: ['d-PC-1', 'd-PC-2'], preview: false }));
    await waitFor(() => expect(screen.queryByTestId('device-script-bar')).toBeNull());
    expect(toast.success).toHaveBeenCalled();
  });

  it('says why when CORE has shared no scripts, and shows the API reason when a run is refused', async () => {
    optionsMock.mockResolvedValue({ scripts: [], blocked: 'CORE has not shared any scripts.' });
    renderView();
    await screen.findByText('PC-1');
    await userEvent.click(screen.getByLabelText('Select PC-1'));
    await userEvent.click(screen.getByRole('button', { name: 'Run script on these machines' }));
    expect((await screen.findByRole('alert')).textContent).toBe('CORE has not shared any scripts.');

    optionsMock.mockResolvedValue({ scripts: [{ id: 7, name: 'Disk Space Scan', one_click: false }], blocked: null });
    runMock.mockRejectedValue(new Error('Permission denied: connectors:write'));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await userEvent.click(screen.getByRole('button', { name: 'Run script on these machines' }));
    await screen.findByLabelText('Script');
    await userEvent.click(screen.getByRole('button', { name: 'See which machines' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Permission denied: connectors:write');
  });
});

describe('where else a machine is filed', () => {
  it('says what a lookalike shares in words', () => {
    expect(matchedText(['serial', 'name'])).toBe('Same serial number and name');
    expect(matchedText(['serial'])).toBe('Same serial number');
    expect(matchedText(['name'])).toBe('Same name');
  });

  it('lists the other records with the same serial or name under any client, and says so when there are none', async () => {
    elsewhereMock.mockReset().mockResolvedValueOnce({
      device_id: 'd-PC-1', hostname: 'PC-1', client_name: 'Acme', tools: ['ninjaone'],
      items: [{ device_id: 'x1', hostname: 'PC-1', client_name: 'Acme (older)', same_client: false, serial_number: 'ABC123', tools: ['huntress'], last_seen: NOW, matched_on: ['serial', 'name'] }],
    });
    renderView();
    await userEvent.click(await screen.findByText('PC-1'));
    await userEvent.click(await screen.findByRole('button', { name: 'Where else is this machine filed?' }));
    expect(elsewhereMock).toHaveBeenCalledWith('d-PC-1');
    const box = await screen.findByTestId('where-else');
    await waitFor(() => expect(box.textContent).toContain('Acme (older)'));
    expect(box.textContent).toContain('Same serial number and name (ABC123)');
    elsewhereMock.mockResolvedValueOnce({ device_id: 'd-PC-1', hostname: 'PC-1', client_name: 'Acme', tools: ['ninjaone'], items: [] });
    await userEvent.click(within(box).getByRole('button'));
    expect(await within(box).findByText(/No other device, under any client/)).toBeTruthy();
  });
});
