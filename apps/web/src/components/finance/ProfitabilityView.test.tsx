import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/saveFile', () => ({ saveText: vi.fn() }));

import { ProfitabilityView, money, monthLabel, pct, sortRows } from './ProfitabilityView';

const row = (over: Record<string, unknown> = {}) => ({ client_id: '5', client_name: 'Acme Dental', revenue: 1000, invoices: 2, hours: 6.5, labor: 900, after_labor: 100, margin_percent: 10, software_per_run: 123.45, ...over });
const body = (over: Record<string, unknown> = {}) => ({
  received_at: '2026-11-15T10:00:00Z',
  months: ['2026-09', '2026-10'],
  report: {
    month: '2026-10',
    rows: [row(), row({ client_id: '6', client_name: 'Birch Law', revenue: 400.5, labor: 100, after_labor: 300.5, margin_percent: 75, hours: 1, software_per_run: null }), row({ client_id: '7', client_name: 'Loss Maker', revenue: 200, labor: 500, after_labor: -300, margin_percent: -150 })],
    totals: { revenue: 1600.5, labor: 1500, after_labor: 100.5, hours: 12, margin_percent: 6.3 },
    unmatched_hours: [{ client: 'Nobody Invoiced LLC', hours: 3, labor: 195 }],
    agents_on_default_rate: [{ agent_id: '40', name: 'Dan Kemp', hours: 8 }],
    default_rate: 65,
  },
  rates: [{ scope: 'team', key: 'Support', hourly_rate: 100 }],
  agents: [{ id: '40', name: 'Dan Kemp', team: 'Support', active: true }, { id: '41', name: 'Vic Cio', team: 'vCIO', active: true }],
  note: 'Revenue is what HaloPSA invoiced.',
  ...over,
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b), text: () => Promise.resolve('Client,Revenue\n') });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(() => answer(body()));
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('writes money, percentages and months for people', () => {
    expect(money(1234.5)).toBe('$1,234.50');
    expect(money(null)).toBe('—');
    expect(pct(10)).toBe('10%');
    expect(pct(null)).toBe('—');
    expect(monthLabel('2026-10')).toBe('October 2026');
  });
  it('sorts by the column chosen and puts a missing margin last either way', () => {
    const rows = [row({ client_name: 'B', margin_percent: null }), row({ client_name: 'A', margin_percent: 5 }), row({ client_name: 'C', margin_percent: 50 })];
    expect(sortRows(rows, 'margin_percent', true).map((r) => r.client_name)).toEqual(['C', 'A', 'B']);
    expect(sortRows(rows, 'margin_percent', false).map((r) => r.client_name)).toEqual(['A', 'C', 'B']);
    expect(sortRows(rows, 'client_name', false).map((r) => r.client_name)).toEqual(['A', 'B', 'C']);
  });
  it('sorts the amounts the API sends as text by their value, so 977.12 is not placed between 9820.00 and 9810.27', () => {
    const text = (client_name: string, revenue: string, hours: string) => row({ client_name, revenue: revenue as unknown as number, hours: hours as unknown as number });
    const rows = [text('A', '977.12', '8.41'), text('B', '9820.00', '146.46'), text('C', '9810.27', '46.71'), text('D', '91.56', '1.63')];
    expect(sortRows(rows, 'revenue', true).map((r) => r.client_name)).toEqual(['B', 'C', 'A', 'D']);
    expect(sortRows(rows, 'hours', true).map((r) => r.client_name)).toEqual(['B', 'C', 'A', 'D']);
    expect(sortRows(rows, 'revenue', false).map((r) => r.client_name)).toEqual(['D', 'A', 'C', 'B']);
  });
});

describe('ProfitabilityView', () => {
  it('shows the month, the totals and a row per client, biggest revenue first, and flags a loss', async () => {
    render(<ProfitabilityView />);
    const totals = await screen.findByTestId('profit-totals');
    expect(totals).toHaveTextContent('$1,600.50');
    expect(totals).toHaveTextContent('6.3%');
    const rows = screen.getAllByTestId('profit-row');
    expect(rows.map((r) => within(r).getAllByRole('cell')[0]!.textContent)).toEqual(['Acme Dental', 'Birch Law', 'Loss Maker']);
    expect(rows[0]).toHaveTextContent('$123.45');
    expect(within(rows[2]!).getByText('-$300.00')).toHaveClass('text-red-300');
    expect(screen.getByTestId('profit-unmatched')).toHaveTextContent('Nobody Invoiced LLC: 3 h, $195.00');
    expect(screen.getByTestId('profit-default-agents')).toHaveTextContent('Dan Kemp (8 h)');
    expect(screen.getByText('Team: Support')).toBeInTheDocument();
  });

  it('says nothing has arrived yet instead of showing an empty table', async () => {
    authFetch.mockImplementation(() => answer({ received_at: null, months: [], report: null, rates: [] }));
    render(<ProfitabilityView />);
    expect(await screen.findByTestId('profit-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('profit-table')).toBeNull();
  });

  it('says it needs the finance permission when the API refuses, and shows no money', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<ProfitabilityView />);
    expect(await screen.findByText(/needs the finance permission/)).toBeInTheDocument();
    expect(screen.queryByTestId('profit-totals')).toBeNull();
  });

  it('loads another month when it is chosen, and saves and removes a rate', async () => {
    render(<ProfitabilityView />);
    await screen.findByTestId('profit-totals');
    await userEvent.selectOptions(screen.getByLabelText('Month'), '2026-09');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/profitability?month=2026-09'));

    await userEvent.selectOptions(screen.getByLabelText('Rate for'), 'agent');
    await userEvent.selectOptions(screen.getByLabelText('Agent'), '41');
    await userEvent.type(screen.getByLabelText('Hourly cost'), '150');
    await userEvent.click(screen.getByRole('button', { name: 'Save rate' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/labor-rates', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ scope: 'agent', key: '41', hourly_rate: '150' }) })));

    await userEvent.click(within(screen.getByTestId('profit-rates')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/labor-rates?scope=team&key=Support', expect.objectContaining({ method: 'DELETE' })));
  });

  it('will not save a rate for a team or agent until one is picked', async () => {
    render(<ProfitabilityView />);
    await screen.findByTestId('profit-totals');
    await userEvent.selectOptions(screen.getByLabelText('Rate for'), 'team');
    await userEvent.type(screen.getByLabelText('Hourly cost'), '90');
    expect(screen.getByRole('button', { name: 'Save rate' })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText('Team'), 'Support');
    expect(screen.getByRole('button', { name: 'Save rate' })).toBeEnabled();
  });
});

describe('Profitability: opening a client', () => {
  it('opens what a client\u2019s numbers are made of for the month shown, and closes it again', async () => {
    authFetch.mockImplementation((u: string) =>
      String(u).includes('/profitability/client')
        ? answer({ client_id: '5', client_name: 'Acme Dental', month: '2026-10', revenue: 1000, invoices: 2, invoice_lines: [], invoice_lines_total: 0, free_lines: 0, hours: 0, labor: 0, after_labor: 1000, by_agent: [], by_charge_type: [], recurring: [], tickets: null, invoice_lines_received_at: null })
        : answer(body()),
    );
    render(<ProfitabilityView />);
    await screen.findByTestId('profit-table');
    await userEvent.click(screen.getAllByRole('button', { name: /Where the numbers of Acme Dental come from/ })[0]!);
    expect(await screen.findByTestId('client-profit-detail')).toHaveTextContent('Acme Dental: where the numbers come from');
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('/profitability/client?client_id=5&month=2026-10'))).toBe(true);
    await userEvent.click(within(screen.getByTestId('client-profit-detail')).getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('client-profit-detail')).toBeNull();
  });

  it('opens the same detail, at its tickets, when the hours are pressed', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    authFetch.mockImplementation((u: string) =>
      String(u).includes('/profitability/client')
        ? answer({ client_id: '5', client_name: 'Acme Dental', month: '2026-10', revenue: 1000, invoices: 2, invoice_lines: [], invoice_lines_total: 0, free_lines: 0, hours: 6.5, labor: 0, after_labor: 0, by_agent: [], by_charge_type: [], recurring: [], tickets: { rows: [{ ticket_id: '700', summary: 'Quarterly review', hours: 2.5, entries: 2, agents: ['Dan Kemp'] }], other_hours: 0 }, invoice_lines_received_at: null })
        : answer(body()),
    );
    render(<ProfitabilityView />);
    await screen.findByTestId('profit-table');
    await userEvent.click(screen.getAllByRole('button', { name: /Every ticket behind the .* hours of Acme Dental/ })[0]!);
    expect(await screen.findByTestId('detail-ticket-rows')).toHaveTextContent('Quarterly review');
    await waitFor(() => expect(scroll).toHaveBeenCalled());
  });
});
