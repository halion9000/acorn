import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { SoftwareCostsPanel, filterCounted, vendorSummary, type Software, type VendorRow } from './SoftwareCostsPanel';

const vendor = (over: Partial<VendorRow> = {}): VendorRow => ({ vendor: 'Huntress', account: '5500', latest_month: '2026-10', latest_amount: '1170.65', mapped: [], licenses: null, per_license: null, ...over });
const software = (over: Partial<Software> = {}): Software => ({
  have_costs: true,
  latest_month: '2026-10',
  vendors: [
    vendor({ vendor: 'Kaseya', latest_amount: '14048.39', mapped: [{ source: 'halopsa', item: 'Datto backup' }], licenses: 100, per_license: '140.4839' }),
    vendor({ vendor: 'Huntress' }),
    vendor({ vendor: 'Ninjaone LLC', account: '5100', latest_amount: '7132.13' }),
  ],
  counted_items: [{ source: 'halopsa', item: 'Datto backup' }, { source: 'halopsa', item: 'Huntress EDR' }, { source: 'huntress', item: 'Agents' }],
  ...over,
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method ? answer({}, 204) : answer(software())));
});

describe('the pure parts', () => {
  it('words how a vendor stands', () => {
    expect(vendorSummary(vendor())).toBe('No count chosen: spread by revenue');
    expect(vendorSummary(vendor({ mapped: [{ source: 'a', item: 'b' }], licenses: 0 }))).toBe('Counts chosen but none are held: spread by revenue');
    expect(vendorSummary(vendor({ mapped: [{ source: 'a', item: 'b' }], licenses: 40, per_license: '2.5' }))).toBe('40 licenses, about $2.50 each');
  });
  it('finds counts by any word of the tool or item, whatever the case', () => {
    const items = software().counted_items;
    expect(filterCounted(items, 'HUNTRESS').map((c) => c.item)).toEqual(['Huntress EDR', 'Agents']);
    expect(filterCounted(items, 'halopsa edr').map((c) => c.item)).toEqual(['Huntress EDR']);
    expect(filterCounted(items, '')).toHaveLength(3);
    expect(filterCounted(items, 'zzz')).toEqual([]);
  });
});

describe('the software costs panel', () => {
  it('lists the vendors biggest first, add-on before support, with what each billed and how it stands', async () => {
    render(<SoftwareCostsPanel />);
    const table = (await screen.findByTestId('software-costs')).querySelector('table')!;
    const names = () => within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0]!.textContent);
    expect(names()).toEqual(['Kaseya', 'Ninjaone LLC', 'Huntress']);
    expect(within(table).getByText('100 licenses, about $140.48 each')).toBeInTheDocument();
    expect(within(table).getAllByText('No count chosen: spread by revenue')).toHaveLength(2);
    await userEvent.click(within(table).getByRole('button', { name: 'Vendor' }));
    expect(names()).toEqual(['Huntress', 'Kaseya', 'Ninjaone LLC']);
  });

  it('chooses the counts behind a vendor and saves them, replacing what was there', async () => {
    render(<SoftwareCostsPanel />);
    await screen.findByTestId('software-costs');
    await userEvent.click(screen.getByRole('button', { name: 'Choose the counts behind Huntress' }));
    const picker = screen.getByTestId('count-picker');
    fireEvent.change(within(picker).getByLabelText('Find a count'), { target: { value: 'huntress' } });
    await userEvent.click(within(picker).getByLabelText('halopsa: Huntress EDR'));
    await userEvent.click(within(picker).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([, i]) => i?.method === 'PUT')).toBe(true));
    const put = authFetch.mock.calls.find(([, i]) => i?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/finance/software/map');
    expect(JSON.parse(put[1].body)).toEqual({ vendor: 'Huntress', counted: [{ source: 'halopsa', item: 'Huntress EDR' }] });
  });

  it('starts a vendor with its current counts ticked, and a count taken off is left out of what is saved', async () => {
    render(<SoftwareCostsPanel />);
    await screen.findByTestId('software-costs');
    await userEvent.click(screen.getByRole('button', { name: 'Choose the counts behind Kaseya' }));
    const picker = screen.getByTestId('count-picker');
    const box = within(picker).getByLabelText('halopsa: Datto backup');
    expect(box).toBeChecked();
    await userEvent.click(box);
    await userEvent.click(within(picker).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([, i]) => i?.method === 'PUT')).toBe(true));
    expect(JSON.parse(authFetch.mock.calls.find(([, i]) => i?.method === 'PUT')![1].body)).toEqual({ vendor: 'Kaseya', counted: [] });
  });

  it('says so when QuickBooks has sent no vendor bills yet', async () => {
    authFetch.mockImplementation(() => answer(software({ have_costs: false, vendors: [], latest_month: null })));
    render(<SoftwareCostsPanel />);
    expect(await screen.findByText(/has not sent the vendor bills yet/)).toBeInTheDocument();
  });
});
