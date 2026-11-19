import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { HistoryPanel, PnlPanel, QboProfitPanel, filterClients, pnlAmount, qboColumns, moneyWhole } from './QboSections';

const answer = (body: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: async () => body });

const PNL = {
  months: ['2026-08', '2026-09'],
  month: '2026-09',
  lines: [
    { depth: 0, kind: 'header', label: 'Income', amount: null },
    { depth: 1, kind: 'line', label: '4000 Managed Service Revenue', amount: 509298.5 },
    { depth: 0, kind: 'total', label: 'Total Income', amount: 509298.5 },
    { depth: 0, kind: 'total', label: 'Net Income', amount: -12.5 },
  ],
};

const qrow = (over: Record<string, unknown> = {}) => ({
  client_key: 'a', client_name: 'Acme Dental', revenue: '1000.00', hours: '6.50', direct_labor: '400.00', labor_trueup: '50.00', addon_software: '20.00', support_software: '10.00', travel: '0.00', equipment: '5.00', hardware: '0.00',
  total_cost: '485.00', gross_profit: '515.00', gross_margin: 51.5, sales_marketing: '0.00', overhead: '100.00', net_income: '415.00', net_margin: 41.5, months_active: 12, ...over,
});

beforeEach(() => authFetch.mockReset());
afterEach(cleanup);

describe('pnlAmount', () => {
  it('leaves a header and an empty cell empty and keeps a negative sign', () => {
    expect(pnlAmount({ depth: 0, kind: 'header', label: 'Income', amount: null })).toBe('');
    expect(pnlAmount({ depth: 1, kind: 'line', label: 'x', amount: 1234.5 })).toBe(pnlAmount({ depth: 1, kind: 'line', label: 'x', amount: 1234.5 }));
    expect(pnlAmount({ depth: 1, kind: 'line', label: 'x', amount: -12.5 })).toContain('12.50');
  });
});

describe('PnlPanel', () => {
  it('shows the lines indented by depth with totals marked, and asks for another month when chosen', async () => {
    authFetch.mockImplementation(() => answer(PNL));
    render(<PnlPanel />);
    const table = await screen.findByTestId('pnl-table');
    expect(within(table).getByText('4000 Managed Service Revenue')).toBeTruthy();
    const rows = within(table).getAllByRole('row');
    expect(rows[1]!.className).toContain('font-medium');
    expect(rows[3]!.className).toContain('font-semibold');
    expect(within(table).getByText('4000 Managed Service Revenue').getAttribute('style')).toContain('32px');
    await userEvent.selectOptions(screen.getByLabelText('P&L month'), '2026-08');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).includes('pnl?month=2026-08'))).toBe(true));
  });

  it('says so before anything has arrived, and when the finance permission is missing', async () => {
    authFetch.mockImplementation(() => answer({ months: [], month: null, lines: [] }));
    const { unmount } = render(<PnlPanel />);
    expect(await screen.findByText(/Nothing has arrived from QuickBooks yet/)).toBeTruthy();
    unmount();
    authFetch.mockImplementation(() => answer({}, 403));
    render(<PnlPanel />);
    expect(await screen.findByText(/needs the finance permission/)).toBeTruthy();
  });
});

describe('qboColumns', () => {
  it('reads money sent as text as numbers and works out the personnel columns the workbook has', () => {
    const c = qboColumns(qrow() as never);
    expect(c.total_personnel).toBe(450);
    expect(c.revenue_less_cos_personnel).toBe(600);
    expect(c.margin_after_personnel).toBe(550);
    expect(c.total_cos).toBe(485);
    expect(c.months_active).toBe(12);
    expect(qboColumns(qrow({ gross_margin: null, net_margin: null }) as never).net_margin).toBeNull();
  });
});

describe('QboProfitPanel', () => {
  it('lists the clients with the workbook columns, sorts a column when pressed, and totals them', async () => {
    authFetch.mockImplementation(() => answer({ months: ['2026-09', '2026-10'], report: { month: '2026-10', rows: [qrow(), qrow({ client_key: 'b', client_name: 'Birch Law', revenue: '4000.00', direct_labor: '10.00', net_income: '3000.00' })], totals: { revenue: '5000.00', direct_labor: '410.00', labor_trueup: '100.00', total_cost: '900.00', gross_profit: '4100.00', gross_margin: 82, net_income: '3415.00', net_margin: 68.3, addon_software: '0', support_software: '0', travel: '0', equipment: '0', hardware: '0', sales_marketing: '0', overhead: '0' } } }));
    render(<QboProfitPanel />);
    const table = await screen.findByTestId('qbo-table');
    const names = () => within(table).getAllByRole('row').slice(1, 3).map((r) => r.querySelector('td')!.textContent);
    expect(names()).toEqual(['Acme Dental', 'Birch Law']);
    await userEvent.click(within(table).getByRole('button', { name: /Total revenue/ }));
    expect(names()).toEqual(['Birch Law', 'Acme Dental']);
    expect(within(table).getByText('Total')).toBeTruthy();
    expect(within(table).getByRole('button', { name: /Months active/ })).toBeTruthy();
  });
});

describe('the wide table', () => {
  it('writes a crowded amount in whole dollars with a dash for nothing', () => {
    expect([moneyWhole(3598.11), moneyWhole(-12.5), moneyWhole(0), moneyWhole(null)]).toEqual(['$3,598', '-$13', '$0', '—']);
  });

  it('shows whole dollars in the cells with the exact amount in the tooltip, and the month as a Month and a Year', async () => {
    authFetch.mockImplementation(() => answer({ months: ['2026-09', '2026-10'], report: { month: '2026-10', rows: [qrow({ revenue: '3598.11' })], totals: {} }, received_at: 'x' }));
    render(<QboProfitPanel />);
    const table = await screen.findByTestId('qbo-table');
    const cell = within(table).getByText('$3,598');
    expect(cell).toHaveAttribute('title', '$3,598.11');
    expect(screen.getByLabelText('QBO month')).toBeInTheDocument();
    expect(screen.getByLabelText('QBO year')).toBeInTheDocument();
  });
});

describe('filterClients', () => {
  const clients = [
    { client: 'Acme Dental', total: 10, by_month: {}, qbo_names: ['Acme Dental', 'Acme Annex'] },
    { client: 'Birch Law', total: 5, by_month: {}, qbo_names: ['Birch Law'] },
  ];
  it('finds a client by its own name or by a QuickBooks customer behind it', () => {
    expect(filterClients(clients, 'annex').map((c) => c.client)).toEqual(['Acme Dental']);
    expect(filterClients(clients, ' LAW ').map((c) => c.client)).toEqual(['Birch Law']);
    expect(filterClients(clients, '')).toBe(clients);
  });
});

describe('HistoryPanel', () => {
  const HIST = {
    months: ['2026-08', '2026-09'],
    clients: [
      { client: 'Acme Dental', total: '270.00', by_month: { '2026-08': '150.00', '2026-09': '120.00' }, qbo_names: ['Acme Annex', 'Acme Dental'] },
      { client: 'Birch Law', total: '70.50', by_month: { '2026-09': '70.50' }, qbo_names: ['Birch Law'] },
    ],
  };
  it('shows each client by month with totals, sorts a month column as numbers and filters', async () => {
    authFetch.mockImplementation(() => answer(HIST));
    render(<HistoryPanel />);
    const table = await screen.findByTestId('history-table');
    const names = () => within(table).getAllByRole('row').slice(1, 3).map((r) => r.querySelector('td')!.textContent);
    expect(names()).toEqual(['Acme Dental', 'Birch Law']);
    expect(within(table).getByText('Acme Dental').getAttribute('title')).toBe('Acme Annex, Acme Dental');
    await userEvent.click(within(table).getByRole('button', { name: /Sep/ }));
    expect(names()).toEqual(['Acme Dental', 'Birch Law']);
    await userEvent.click(within(table).getByRole('button', { name: /Sep/ }));
    expect(names()).toEqual(['Birch Law', 'Acme Dental']);
    await userEvent.type(screen.getByLabelText('Find a client'), 'birch');
    expect(within(table).queryByText('Acme Dental')).toBeNull();
  });
});
