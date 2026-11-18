import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { BillingSyncView, canApprove, filterRows, nextSort, partsText, pushText, signed, sortRows, type SyncRow } from './BillingSyncView';

const row = (over: Partial<SyncRow> = {}): SyncRow => ({
  client_id: 'c1',
  client_name: 'Acme Dental',
  invoice_item: 'Microsoft 365 Business Premium',
  billed: 10,
  counted: 12,
  difference: 2,
  hidden: false,
  can_push: true,
  push: { status: 'none', quantity: null, message: null, by: null, at: null },
  ...over,
});
const data = (rows: SyncRow[] = [row(), row({ client_id: 'c2', client_name: 'Birch Law', billed: 5, counted: 4, difference: -1, can_push: false }), row({ client_id: 'c3', client_name: 'Cedar Co', invoice_item: 'Windows workstations', billed: 3, counted: 5, difference: 2 })]) => ({ generated_at: '2026-11-15T10:00:00Z', rows, hidden: 1 });
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'POST' && String(url).endsWith('/approve')) return answer([{ client_id: 'c1', invoice_item: 'Microsoft 365 Business Premium', ok: true, detail: 'Queued: set to 12 (was 10).' }]);
    if (init?.method === 'POST') return answer({ changed: 1 });
    return answer(data());
  });
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('signs a difference and filters by organization and type', () => {
    expect(signed(2)).toBe('+2');
    expect(signed(-1)).toBe('-1');
    const rows = data().rows;
    expect(filterRows(rows, 'ac', '').map((r) => r.client_name)).toEqual(['Acme Dental']);
    expect(filterRows(rows, '', 'Windows workstations').map((r) => r.client_name)).toEqual(['Cedar Co']);
    expect(filterRows(rows, '', '')).toHaveLength(3);
  });
  it('allows approval only for a mapped client with nothing waiting', () => {
    expect(canApprove(row())).toBe(true);
    expect(canApprove(row({ can_push: false }))).toBe(false);
    expect(canApprove(row({ push: { status: 'pending', quantity: 12, message: null, by: null, at: null } }))).toBe(false);
    expect(canApprove(row({ push: { status: 'failed', quantity: 12, message: 'x', by: null, at: null } }))).toBe(true);
  });
  it('says each push outcome in words', () => {
    expect(pushText(row().push)).toBe('');
    expect(pushText({ status: 'pending', quantity: 12, message: null, by: null, at: null })).toBe('Waiting for CORE: set to 12');
    expect(pushText({ status: 'done', quantity: 12, message: 'Set "X" to 12 (was 10).', by: null, at: null })).toBe('Set "X" to 12 (was 10).');
    expect(pushText({ status: 'failed', quantity: 12, message: 'changed since', by: null, at: null })).toBe('Failed: changed since');
  });
});

describe('the Billing sync page', () => {
  it('says what to do without the billing role', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<BillingSyncView />);
    expect(await screen.findByText(/needs the billing role/)).toBeTruthy();
  });

  it('says nothing differs when nothing does', async () => {
    authFetch.mockImplementation(() => answer({ generated_at: '2026-11-15T10:00:00Z', rows: [], hidden: 0 }));
    render(<BillingSyncView />);
    expect(await screen.findByTestId('sync-empty')).toBeTruthy();
  });

  it('lists the differences, marks an unmapped client, and approves one line', async () => {
    render(<BillingSyncView />);
    const table = await screen.findByTestId('sync-table');
    expect(within(table).getByText('Not mapped to HaloPSA')).toBeTruthy();
    const acme = within(table).getByText('Acme Dental').closest('tr')!;
    await userEvent.click(within(acme).getByRole('button', { name: 'Approve' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find(([u, i]) => String(u).endsWith('/billing/sync/approve') && i?.method === 'POST');
      expect(JSON.parse(post![1].body)).toEqual({ items: [{ client_id: 'c1', invoice_item: 'Microsoft 365 Business Premium' }] });
    });
    expect(await screen.findByText(/Queued: set to 12 \(was 10\)/)).toBeTruthy();
    const birch = within(table).getByText('Birch Law').closest('tr')!;
    expect((within(birch).getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('hides one line with the Hide button next to its Approve button', async () => {
    render(<BillingSyncView />);
    const table = await screen.findByTestId('sync-table');
    const acme = within(table).getByText('Acme Dental').closest('tr')!;
    await userEvent.click(within(acme).getByRole('button', { name: 'Hide' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find(([u]) => String(u).endsWith('/billing/sync/hide'));
      expect(JSON.parse(post![1].body)).toEqual({ items: [{ client_id: 'c1', invoice_item: 'Microsoft 365 Business Premium' }], hidden: true });
    });
  });

  it('approves only the selected lines that can be approved, and hides the selection', async () => {
    render(<BillingSyncView />);
    await screen.findByTestId('sync-table');
    await userEvent.click(screen.getByLabelText('Select Acme Dental Microsoft 365 Business Premium'));
    await userEvent.click(screen.getByLabelText('Select Birch Law Microsoft 365 Business Premium'));
    await userEvent.click(screen.getByRole('button', { name: 'Approve selected (1)' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find(([u]) => String(u).endsWith('/approve'));
      expect(JSON.parse(post![1].body).items).toHaveLength(1);
    });
    await userEvent.click(screen.getByLabelText('Select Cedar Co Windows workstations'));
    await userEvent.click(screen.getByRole('button', { name: 'Hide selected' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find(([u]) => String(u).endsWith('/billing/sync/hide'));
      expect(JSON.parse(post![1].body)).toEqual({ items: [{ client_id: 'c3', invoice_item: 'Windows workstations' }], hidden: true });
    });
  });

  it('asks for the hidden lines when told to and filters by organization', async () => {
    render(<BillingSyncView />);
    await screen.findByTestId('sync-table');
    await userEvent.type(screen.getByLabelText('Organization'), 'birch');
    expect(within(screen.getByTestId('sync-table')).queryByText('Acme Dental')).toBeNull();
    await userEvent.click(screen.getByLabelText(/Show hidden/));
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('show_hidden=true'))).toBe(true));
  });
});

describe('sorting the sync rows', () => {
  const rows = [
    row({ client_id: 'a', client_name: 'beta', billed: 5, counted: 0, difference: -5 }),
    row({ client_id: 'b', client_name: 'Alpha', billed: 100, counted: 7, difference: -93, can_push: false }),
    row({ client_id: 'c', client_name: 'Gamma', billed: 8, counted: 20, difference: 12, push: { status: 'failed', quantity: 20, message: 'no', by: null, at: null } }),
  ];
  const names = (key: Parameters<typeof sortRows>[1], dir: 'asc' | 'desc') => sortRows(rows, key, dir).map((r) => r.client_name);

  it('orders by text without regard to case, by number, by the size of the difference, and by status', () => {
    expect(names('client_name', 'asc')).toEqual(['Alpha', 'beta', 'Gamma']);
    expect(names('client_name', 'desc')).toEqual(['Gamma', 'beta', 'Alpha']);
    expect(names('billed', 'desc')).toEqual(['Alpha', 'Gamma', 'beta']);
    expect(names('counted', 'asc')).toEqual(['beta', 'Alpha', 'Gamma']);
    expect(names('difference', 'asc')).toEqual(['Alpha', 'beta', 'Gamma']);
    expect(names('size', 'desc')).toEqual(['Alpha', 'Gamma', 'beta']);
    expect(names('status', 'asc')).toEqual(['Alpha', 'Gamma', 'beta']);
  });
  it('keeps the order given for no column and for equal values, and a header click starts text ascending and numbers largest first, then flips', () => {
    expect(sortRows(rows, null, 'asc')).toBe(rows);
    expect(sortRows([row({ client_name: 'x', billed: 1 }), row({ client_name: 'y', billed: 1 })], 'billed', 'asc').map((r) => r.client_name)).toEqual(['x', 'y']);
    expect(nextSort({ key: null, dir: 'desc' }, 'client_name')).toEqual({ key: 'client_name', dir: 'asc' });
    expect(nextSort({ key: null, dir: 'desc' }, 'billed')).toEqual({ key: 'billed', dir: 'desc' });
    expect(nextSort({ key: 'billed', dir: 'desc' }, 'billed')).toEqual({ key: 'billed', dir: 'asc' });
  });
  it('writes the counted number out from its parts, or says none is mapped', () => {
    expect(partsText(row({ parts: [{ source: 'threatmate', item: 'Internal assets', count: 0 }, { source: 'threatmate', item: 'Users', count: 12 }] }))).toBe('threatmate Internal assets: 0 + threatmate Users: 12');
    expect(partsText(row({ parts: [] }))).toBe('No tool count is mapped to this invoice line.');
    expect(partsText(row())).toBe('No tool count is mapped to this invoice line.');
  });
});

describe('the Billing sync page: sorting and where a number comes from', () => {
  it('sorts when a header is clicked, marks the column, and flips on a second click', async () => {
    render(<BillingSyncView />);
    const table = await screen.findByTestId('sync-table');
    const order = () => within(table).getAllByRole('row').slice(1).map((r) => r.textContent ?? '').map((t) => (t.match(/Acme Dental|Birch Law|Cedar Co/) ?? [''])[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Sort by Organization' }));
    expect(order()).toEqual(['Acme Dental', 'Birch Law', 'Cedar Co']);
    expect(screen.getByRole('columnheader', { name: /Organization/ })).toHaveAttribute('aria-sort', 'ascending');
    await userEvent.click(screen.getByRole('button', { name: /Sort by Organization/ }));
    expect(order()).toEqual(['Cedar Co', 'Birch Law', 'Acme Dental']);
    expect(screen.getByRole('columnheader', { name: /Organization/ })).toHaveAttribute('aria-sort', 'descending');
  });

  it('opens a line to show which tool counts make up the counted number', async () => {
    authFetch.mockImplementation(() => answer(data([row({ parts: [{ source: 'threatmate', item: 'Internal assets', count: 12 }] })])));
    render(<BillingSyncView />);
    await screen.findByTestId('sync-table');
    await userEvent.click(screen.getByRole('button', { name: /Where the counted number of Acme Dental/ }));
    const detail = screen.getByTestId('sync-detail');
    expect(detail).toHaveTextContent('HaloPSA bills 10 of Microsoft 365 Business Premium. A.C.O.R.N counts 12 as: threatmate Internal assets: 12.');
    expect(within(detail).getByRole('link', { name: /Licenses/ })).toHaveAttribute('href', '/settings/billing');
    await userEvent.click(screen.getByRole('button', { name: /Where the counted number of Acme Dental/ }));
    expect(screen.queryByTestId('sync-detail')).toBeNull();
  });
});
