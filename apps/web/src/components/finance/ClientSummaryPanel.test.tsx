import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientSummaryPanel, filterSummary, type SummaryRow } from './ClientSummaryPanel';

const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: async () => b });
const row = (over: Partial<SummaryRow> = {}): SummaryRow => ({
  client_key: 'a', client_name: 'Acme Dental', industry: 'Dental', for_profit: true, months_active: 12, ytd_revenue: '1000.00', ytd_net_income: '250.00', ytd_net_margin: 25, bracket: '20% to 29%',
  by_month: { '2026-09': { revenue: '500', net_income: '100.00', net_margin: 20 }, '2026-10': { revenue: '500', net_income: '150.00', net_margin: 30 } }, ...over,
});
const DATA = {
  received_at: '2026-11-18T10:00:00Z', available: ['2026-08', '2026-09', '2026-10'], months: ['2026-09', '2026-10'], through: '2026-10',
  rows: [row(), row({ client_key: 'b', client_name: 'Birch Church', industry: 'Church', for_profit: false, ytd_net_income: '-40.00', ytd_net_margin: -4, bracket: 'Not profitable', ytd_revenue: '900.00', by_month: { '2026-10': { revenue: '900', net_income: '-40.00', net_margin: -4 } } })],
};

beforeEach(() => authFetch.mockReset());
afterEach(cleanup);

describe('filterSummary', () => {
  const rows = DATA.rows;
  it('narrows by industry, for-profit and typed text together', () => {
    expect(filterSummary(rows, 'Dental', 'all', '').map((r) => r.client_name)).toEqual(['Acme Dental']);
    expect(filterSummary(rows, 'all', 'non', '').map((r) => r.client_name)).toEqual(['Birch Church']);
    expect(filterSummary(rows, 'all', 'for', 'ACME').map((r) => r.client_name)).toEqual(['Acme Dental']);
    expect(filterSummary(rows, 'Church', 'for', '')).toEqual([]);
    expect(filterSummary([row({ industry: '' })], 'No industry', 'all', '')).toHaveLength(1);
  });
});

describe('ClientSummaryPanel', () => {
  it('shows each client with its year to date, band and month columns, sorts, filters and totals', async () => {
    authFetch.mockImplementation(() => answer(DATA));
    render(<ClientSummaryPanel />);
    const table = await screen.findByTestId('summary-table');
    const names = () => within(table).getAllByRole('row').slice(1, 3).map((r) => r.querySelector('td')!.textContent);
    expect(names()).toEqual(['Acme Dental', 'Birch Church']);
    expect(within(table).getByText('20% to 29%')).toBeTruthy();
    expect(within(table).getByText('Not profitable')).toBeTruthy();
    await userEvent.click(within(table).getByRole('button', { name: /YTD net income/ }));
    expect(names()).toEqual(['Acme Dental', 'Birch Church']);
    await userEvent.click(within(table).getByRole('button', { name: /YTD net income/ }));
    expect(names()).toEqual(['Birch Church', 'Acme Dental']);
    await userEvent.selectOptions(screen.getByLabelText('For-profit or non-profit'), 'for');
    expect(within(table).queryByText('Birch Church')).toBeNull();
    expect(within(table).getByText('Total (1)')).toBeTruthy();
  });

  it('asks for another month when chosen, and says when nothing has arrived or the permission is missing', async () => {
    authFetch.mockImplementation(() => answer(DATA));
    const { unmount } = render(<ClientSummaryPanel />);
    await screen.findByTestId('summary-table');
    await userEvent.selectOptions(screen.getByLabelText('Summary month'), '2026-09');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).includes('summary?month=2026-09'))).toBe(true));
    unmount();
    authFetch.mockImplementation(() => answer({ received_at: null, months: [], through: null, rows: [] }));
    const second = render(<ClientSummaryPanel />);
    expect(await screen.findByText(/Nothing has arrived from HaloPSA yet/)).toBeTruthy();
    second.unmount();
    authFetch.mockImplementation(() => answer({}, 403));
    render(<ClientSummaryPanel />);
    expect(await screen.findByText(/needs the finance permission/)).toBeTruthy();
  });
});
