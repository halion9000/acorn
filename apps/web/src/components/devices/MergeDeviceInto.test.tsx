import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), mergeDuplicates: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), devicesApi: { list: api.list, mergeDuplicates: api.mergeDuplicates } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { ApiError, type DeviceRow } from '@/lib/api';
import { MergeDeviceInto } from './MergeDeviceInto';

const dev = (over: Partial<DeviceRow>): DeviceRow =>
  ({ id: 'd1', tenant_id: 'c1', client_name: 'Acme', hostname: 'AANPC-AZURE', serial_number: null, os: null, os_version: null, manufacturer: null, model: null, ip_addresses: [], last_seen: '2026-11-13T00:00:00Z', first_seen: '2026-10-15T00:00:00Z', sources: [{ vendor: 'huntress', name: 'AANPC-AZURE', last_seen: '2026-11-13T00:00:00Z', details: {} }], ...over }) as DeviceRow;

const THIS = dev({});
const OTHER = dev({ id: 'd2', hostname: 'AANPCBDCAZURE', serial_number: '0000-0011', sources: [{ vendor: 'ninjaone', name: 'AANPCBDCAZURE', last_seen: '2026-11-13T00:00:00Z', details: {} }] });

beforeEach(() => {
  api.list.mockReset().mockResolvedValue({ items: [THIS, OTHER], total: 2, page: 1, pages: 1, page_size: 8, summary: {} });
  api.mergeDuplicates.mockReset().mockResolvedValue({});
  api.toast.success.mockReset();
});

describe('Merge into another device', () => {
  it('searches the same client, leaves this device out, shows the two side by side, and merges this one into the chosen one', async () => {
    const onMerged = vi.fn();
    const user = userEvent.setup();
    render(<MergeDeviceInto device={THIS} onMerged={onMerged} />);
    await user.click(screen.getByRole('button', { name: /Merge into another device/ }));
    await user.type(screen.getByLabelText('Find the device to merge into'), 'AANPC');
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ clientId: 'c1', search: 'AANPC', pageSize: 8 })));
    const choice = await screen.findByRole('button', { name: /AANPCBDCAZURE/ });
    expect(screen.queryByRole('button', { name: /^AANPC-AZURE/ })).toBeNull(); // itself is not offered
    await user.click(choice);
    const dialog = screen.getByRole('dialog', { name: 'Merge these two devices?' });
    expect(dialog).toHaveTextContent('AANPC-AZURE is folded into AANPCBDCAZURE');
    expect(within(screen.getByTestId('merge-compare')).getByText('0000-0011')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Yes, merge' }));
    // The chosen device is the one that STAYS (keep), this one goes (remove).
    await waitFor(() => expect(api.mergeDuplicates).toHaveBeenCalledWith('d2', 'd1', false));
    expect(api.toast.success).toHaveBeenCalledWith('AANPC-AZURE merged into AANPCBDCAZURE');
    expect(onMerged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  const refusal = (status: number, detail: string) => new ApiError(`API ${status} - /api/v1/devices/duplicates/merge`, status, JSON.stringify({ detail }));
  const choose = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: /Merge into another device/ }));
    await user.type(screen.getByLabelText('Find the device to merge into'), 'AANPC');
    await user.click(await screen.findByRole('button', { name: /AANPCBDCAZURE/ }));
  };

  it('says the server\u2019s reason in its own words, not the address that failed, and cancel merges nothing', async () => {
    api.mergeDuplicates.mockRejectedValue(refusal(400, 'The device it was merged into no longer exists.'));
    const onMerged = vi.fn();
    const user = userEvent.setup();
    render(<MergeDeviceInto device={THIS} onMerged={onMerged} />);
    await choose(user);
    await user.click(screen.getByRole('button', { name: 'Yes, merge' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The device it was merged into no longer exists.');
    expect(alert).not.toHaveTextContent('/api/v1');
    expect(screen.queryByTestId('same-machine-note')).toBeNull();
    expect(screen.queryByRole('button', { name: /merge anyway/ })).toBeNull(); // only the serial refusal offers it
    expect(onMerged).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.mergeDuplicates).toHaveBeenCalledTimes(1);
  });

  it('when the two have different serial numbers it says so and offers to merge anyway, as the same machine, on a second deliberate press', async () => {
    api.mergeDuplicates.mockRejectedValueOnce(refusal(409, 'These have different serial numbers, so they are different machines.'));
    const onMerged = vi.fn();
    const user = userEvent.setup();
    render(<MergeDeviceInto device={THIS} onMerged={onMerged} />);
    await choose(user);
    await user.click(screen.getByRole('button', { name: 'Yes, merge' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('These have different serial numbers, so they are different machines.');
    expect(screen.getByTestId('same-machine-note')).toHaveTextContent('virtual machine can carry two serial numbers');
    expect(api.mergeDuplicates).toHaveBeenCalledWith('d2', 'd1', false);
    expect(screen.queryByRole('button', { name: 'Yes, merge' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'They are the same machine: merge anyway' }));
    await waitFor(() => expect(api.mergeDuplicates).toHaveBeenLastCalledWith('d2', 'd1', true));
    expect(onMerged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not search for fewer than two letters, and says so when nothing matches', async () => {
    api.list.mockResolvedValue({ items: [THIS], total: 1, page: 1, pages: 1, page_size: 8, summary: {} });
    const user = userEvent.setup();
    render(<MergeDeviceInto device={THIS} onMerged={() => undefined} />);
    await user.click(screen.getByRole('button', { name: /Merge into another device/ }));
    await user.type(screen.getByLabelText('Find the device to merge into'), 'A');
    await new Promise((r) => setTimeout(r, 350));
    expect(api.list).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText('Find the device to merge into'), 'B');
    expect(await screen.findByText('No other device of this client matches.')).toBeInTheDocument();
  });
});
