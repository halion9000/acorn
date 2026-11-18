import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { CostTransactionsPanel, filterTransactions, type CostTx } from './CostTransactionsPanel';

const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: async () => b });
const tx = (over: Partial<CostTx> = {}): CostTx => ({ account: '5805', date: '2026-09-02', type: 'Expense', name: 'Urban Bird', customer: 'Acme Annex', client: 'Acme Dental', memo: 'Lunch', split: 'Ramp Card', amount: '23.40', ...over });
const DATA = {
  months: ['2026-08', '2026-09'], month: '2026-09', kind: 'travel',
  rows: [tx(), tx({ date: '2026-09-03', name: 'Hotel', client: 'Birch Law', customer: 'Birch Law', memo: 'Two nights', amount: '200.00' })],
  by_client: [{ client: 'Birch Law', total: '200.00' }, { client: 'Acme Dental', total: '23.40' }], total: '223.40',
};

beforeEach(() => authFetch.mockReset());
afterEach(cleanup);

describe('filterTransactions', () => {
  it('finds a transaction by client, customer, vendor or memo in any case', () => {
    const rows = DATA.rows;
    expect(filterTransactions(rows, 'ANNEX').map((r) => r.name)).toEqual(['Urban Bird']);
    expect(filterTransactions(rows, 'nights').map((r) => r.name)).toEqual(['Hotel']);
    expect(filterTransactions(rows, '')).toBe(rows);
  });
});

describe('CostTransactionsPanel', () => {
  it('lists the transactions with the client and totals by client, sorts the amount column and filters', async () => {
    authFetch.mockImplementation(() => answer(DATA));
    render(<CostTransactionsPanel kind="travel" />);
    const table = await screen.findByTestId('tx-table');
    const names = () => within(table).getAllByRole('row').slice(1, 3).map((r) => r.querySelectorAll('td')[3]!.textContent);
    expect(names()).toEqual(['Urban Bird', 'Hotel']);
    expect(within(screen.getByTestId('tx-by-client')).getByText('Birch Law')).toBeTruthy();
    await userEvent.click(within(table).getByRole('button', { name: /Amount/ }));
    expect(names()).toEqual(['Hotel', 'Urban Bird']);
    await userEvent.type(screen.getByLabelText('Find a transaction'), 'lunch');
    expect(within(table).queryByText('Hotel')).toBeNull();
    expect(within(table).getByText('Total (1)')).toBeTruthy();
    expect(authFetch.mock.calls[0]![0]).toContain('kind=travel');
  });

  it('asks for the other kind and another month, and says when there are no transactions, nothing has arrived or the permission is missing', async () => {
    authFetch.mockImplementation(() => answer({ ...DATA, kind: 'hardware', rows: [], by_client: [], total: 0 }));
    const { unmount } = render(<CostTransactionsPanel kind="hardware" />);
    expect(await screen.findByTestId('tx-empty')).toHaveTextContent('No hardware transactions in September 2026.');
    await userEvent.selectOptions(screen.getByLabelText('Transactions month'), '2026-08');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).includes('kind=hardware&month=2026-08'))).toBe(true));
    unmount();
    authFetch.mockImplementation(() => answer({ months: [], month: null, kind: 'travel', rows: [], by_client: [], total: 0 }));
    const second = render(<CostTransactionsPanel kind="travel" />);
    expect(await screen.findByText(/Nothing has arrived from QuickBooks yet/)).toBeTruthy();
    second.unmount();
    authFetch.mockImplementation(() => answer({}, 403));
    render(<CostTransactionsPanel kind="travel" />);
    expect(await screen.findByText(/needs the finance permission/)).toBeTruthy();
  });
});
