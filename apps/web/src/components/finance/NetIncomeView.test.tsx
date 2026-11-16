import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/saveFile', () => ({ saveText: vi.fn() }));

import { COMPANY_WIDE, NetIncomeView, missingNote, parseMasterCsv } from './NetIncomeView';

const zeros = { labor_trueup: 0, addon_software: 0, support_software: 0, travel: 0, equipment: 0, hardware: 0, sales_marketing: 0, overhead: 0 };
const row = (over: Record<string, unknown> = {}) => ({
  client_key: 'acmedentalinc',
  client_name: 'Acme Dental',
  revenue: 1000,
  hours: 6.5,
  direct_labor: 422.5,
  ...zeros,
  total_cost: 422.5,
  gross_profit: 577.5,
  gross_margin: 57.8,
  net_income: 577.5,
  net_margin: 57.8,
  industry: 'Dental',
  non_profit: false,
  new_client: false,
  ...over,
});
const analysis = (over: Record<string, unknown> = {}) => ({
  received_at: '2026-11-15T10:00:00Z',
  months: ['2026-09', '2026-10'],
  report: {
    month: '2026-10',
    rows: [row(), row({ client_key: 'birchlaw', client_name: 'Birch Law', revenue: 400.5, net_income: -76.77, net_margin: -19.2, new_client: true })],
    totals: { revenue: 1400.5, direct_labor: 487.5, ...zeros, gross_profit: 840, gross_margin: 60, net_income: 500.73, net_margin: 35.8 },
    missing: ['addon_software', 'equipment'],
    unplaced: { overhead: 10 },
    new_clients: [{ client_key: 'birchlaw', client_name: 'Birch Law', revenue: 400.5 }],
  },
  industries: [{ industry: 'Dental', clients: 1, non_profit_clients: 0, revenue: 1000, gross_profit: 577.5, net_income: 577.5, gross_margin: 57.8, net_margin: 57.8 }],
  hours: {
    available_hours_per_person: 160,
    total_hours: 10.5,
    by_function: [{ function: 'No Charge', billable: false, hours: 3, cost: 195, share_percent: 28.6 }],
    by_person: [{ agent_id: '40', name: 'Dan Kemp', team: 'Support', hours: 8, billable_hours: 5, utilization_percent: 3.1 }],
  },
  annual: {
    months: ['2026-09', '2026-10'],
    rows: [
      { client_key: 'acmedentalinc', client_name: 'Acme Dental', revenue: 1900, net_income: 497.17, net_margin: 26.2, rank: 1, tier: 'Top 20', bottom_20: false, target_margin: 25, meets_target: true },
      { client_key: 'birchlaw', client_name: 'Birch Law', revenue: 400.5, net_income: -76.77, net_margin: -19.2, rank: 2, tier: 'Top 20', bottom_20: false, target_margin: 20, meets_target: false },
    ],
  },
  note: 'Costs are shared out to the cent.',
  ...over,
});
const inputs = () => ({ costs: [{ month: '2026-10', category: 'travel', client_name: 'Acme Dental', source: 'manual', amount: 50, note: '' }], master: [{ client_key: 'acmedentalinc', client_name: 'Acme Dental', industry: 'Dental', non_profit: false, target_margin: 25 }], available_hours_per_month: 160, categories: ['payroll_cogs', 'travel', 'overhead'] });
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => answer(url.includes('/inputs') ? inputs() : analysis()));
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('names the parts of the number that are not entered, or says all are', () => {
    expect(missingNote(['addon_software', 'equipment'])).toBe('Not entered for this month, so counted as zero: Add-on software, Equipment.');
    expect(missingNote([])).toBe('Every cost category has an entry for this month.');
  });
  it('reads the master sheet from CSV: header skipped, quoted commas kept, non-profit recognized', () => {
    const csv = ['Client,Industry,Non-profit', '"Acme Dental, Inc.",Medical,For-Profit', '', 'A Glimmer of Hope,Charity,Non-Profit', ',Empty,No', 'Birch Law,Legal,yes'].join('\r\n');
    expect(parseMasterCsv(csv)).toEqual([
      { client_name: 'Acme Dental, Inc.', industry: 'Medical', non_profit: false, target_margin: null },
      { client_name: 'A Glimmer of Hope', industry: 'Charity', non_profit: true, target_margin: null },
      { client_name: 'Birch Law', industry: 'Legal', non_profit: true, target_margin: null },
    ]);
    expect(parseMasterCsv('')).toEqual([]);
  });
  it('knows which categories are company-wide', () => {
    expect(COMPANY_WIDE).toEqual(['payroll_cogs', 'sales_marketing', 'overhead']);
  });
});

describe('the Net income page', () => {
  it('says so when the permission is missing', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<NetIncomeView />);
    expect(await screen.findByText(/needs the finance permission/)).toBeTruthy();
  });

  it('says nothing has arrived yet but still offers the inputs', async () => {
    authFetch.mockImplementation((url: string) => answer(url.includes('/inputs') ? inputs() : analysis({ received_at: null, months: [], report: null, industries: [], hours: null, annual: null })));
    render(<NetIncomeView />);
    expect(await screen.findByTestId('net-empty')).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: 'Inputs' }));
    expect(screen.getByTestId('inputs-tab')).toBeTruthy();
  });

  it('shows each client from revenue to net income, flags new clients, names what is missing and what no client could carry', async () => {
    render(<NetIncomeView />);
    const table = await screen.findByTestId('net-table');
    expect(within(table).getByText('Acme Dental')).toBeTruthy();
    expect(within(table).getByText('new')).toBeTruthy();
    expect(within(table).getAllByText('-$76.77').length).toBeGreaterThan(0);
    expect(screen.getByTestId('missing-note').textContent).toContain('Add-on software, Equipment');
    expect(screen.getByTestId('unplaced-note').textContent).toContain('Overhead (G&A) $10.00');
  });

  it('switches between the sheets: new clients, industries, hours and the ranking', async () => {
    render(<NetIncomeView />);
    await screen.findByTestId('net-table');
    await userEvent.click(screen.getByRole('tab', { name: 'New clients' }));
    expect(within(screen.getByTestId('new-clients')).getByText(/Birch Law/)).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: 'By industry' }));
    expect(within(screen.getByTestId('industry-table')).getByText('Dental')).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: 'Hours and utilization' }));
    expect(within(screen.getByTestId('hours-tab')).getByText('not billable')).toBeTruthy();
    expect(within(screen.getByTestId('hours-tab')).getByText('3.1%')).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: 'Ranking' }));
    const rank = screen.getByTestId('rank-table');
    expect(within(rank).getByText(/26.2% meets 25%/)).toBeTruthy();
    expect(within(rank).getByText(/-19.2% below 20%/)).toBeTruthy();
  });

  it('saves a company-wide cost without a client, and a client cost with one', async () => {
    render(<NetIncomeView />);
    await screen.findByTestId('net-table');
    await userEvent.click(screen.getByRole('tab', { name: 'Inputs' }));
    await userEvent.selectOptions(screen.getByLabelText('Category'), 'overhead');
    expect(screen.queryByLabelText('Client')).toBeNull();
    await userEvent.type(screen.getByLabelText('Amount'), '140.05');
    await userEvent.click(screen.getByRole('button', { name: /Save for October 2026/ }));
    await waitFor(() => {
      const put = authFetch.mock.calls.find(([u, i]) => String(u).endsWith('/profitability/costs') && i?.method === 'PUT');
      expect(JSON.parse(put![1].body)).toEqual({ month: '2026-10', category: 'overhead', client_name: '', amount: '140.05', note: '' });
    });
    await userEvent.selectOptions(screen.getByLabelText('Category'), 'travel');
    await userEvent.type(screen.getByLabelText('Client'), 'Acme Dental');
    await userEvent.type(screen.getByLabelText('Amount'), '75');
    await userEvent.click(screen.getByRole('button', { name: /Save for October 2026/ }));
    await waitFor(() => {
      const puts = authFetch.mock.calls.filter(([u, i]) => String(u).endsWith('/profitability/costs') && i?.method === 'PUT');
      expect(JSON.parse(puts[1]![1].body)).toMatchObject({ category: 'travel', client_name: 'Acme Dental', amount: '75' });
    });
  });

  it('removes a typed cost and saves a client master row with no target as null', async () => {
    render(<NetIncomeView />);
    await screen.findByTestId('net-table');
    await userEvent.click(screen.getByRole('tab', { name: 'Inputs' }));
    await userEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]!);
    await waitFor(() => expect(authFetch.mock.calls.some(([u, i]) => String(u).includes('/profitability/costs?month=2026-10&category=travel&client_name=Acme%20Dental') && i?.method === 'DELETE')).toBe(true));
    await userEvent.type(screen.getByLabelText('Master client'), 'Birch Law');
    await userEvent.type(screen.getByLabelText('Industry'), 'Legal');
    await userEvent.click(screen.getByRole('button', { name: 'Save client' }));
    await waitFor(() => {
      const put = authFetch.mock.calls.find(([u, i]) => String(u).endsWith('/profitability/clients') && i?.method === 'PUT');
      expect(JSON.parse(put![1].body)).toEqual({ client_name: 'Birch Law', industry: 'Legal', non_profit: false, target_margin: null });
    });
  });

  it('imports pasted master rows in one call', async () => {
    render(<NetIncomeView />);
    await screen.findByTestId('net-table');
    await userEvent.click(screen.getByRole('tab', { name: 'Inputs' }));
    await userEvent.click(screen.getByLabelText('Client master CSV'));
    await userEvent.paste(['Birch Law,Legal,For-Profit', 'A Glimmer of Hope,Charity,Non-Profit'].join('\n'));
    await userEvent.click(screen.getByRole('button', { name: 'Import 2 clients' }));
    await waitFor(() => {
      const put = authFetch.mock.calls.find(([u, i]) => String(u).endsWith('/profitability/clients/import') && i?.method === 'PUT');
      expect(JSON.parse(put![1].body).rows).toHaveLength(2);
    });
  });
});
