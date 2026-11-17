import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientProfitDetail, linesNote, type ClientDetail } from './ClientProfitDetail';

const detail = (over: Partial<ClientDetail> = {}): ClientDetail => ({
  client_id: '5', client_name: 'Acme Dental', month: '2026-10', revenue: 1000, invoices: 2,
  invoice_lines: [
    { item: 'Managed Services', category: 'Services', quantity: 1, amount: 800, free: false },
    { item: 'Microsoft 365', category: 'Software', quantity: 20, amount: 200, free: false },
    { item: 'ThreatMate (Included)', category: 'Software', quantity: 25, amount: 0, free: true },
  ],
  invoice_lines_total: 1000, free_lines: 1, hours: 6.5, labor: 442.5, after_labor: 557.5,
  by_agent: [{ agent_id: '40', name: 'Dan Kemp', hours: 4, rate: 70, rate_source: 'agent', cost: 280 }, { agent_id: '41', name: 'Vic Cio', hours: 2.5, rate: 65, rate_source: 'default', cost: 162.5 }],
  by_charge_type: [{ charge_type: 'Remote Support', hours: 4 }, { charge_type: 'vCIO', hours: 2.5 }],
  recurring: [{ item: 'Microsoft 365', quantity: 20, unit_price: 10, unit_cost: 8, free: false, cost_per_run: 160 }, { item: 'ThreatMate (Included)', quantity: 25, unit_price: 0, unit_cost: 1.5, free: true, cost_per_run: 37.5 }],
  tickets: null, invoice_lines_received_at: '2026-11-16T10:00:00Z', ...over,
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

describe('the client detail under Profitability', () => {
  beforeEach(() => {
    authFetch.mockReset();
    authFetch.mockImplementation(() => answer(detail()));
  });
  afterEach(() => cleanup());

  it('shows the invoice lines with the free ones marked, the recurring lines, and the hours by person with where each rate came from', async () => {
    render(<ClientProfitDetail clientId="5" month="2026-10" onClose={() => {}} />);
    const lines = await screen.findByTestId('detail-invoice-lines');
    expect(within(lines).getByText('Managed Services')).toBeTruthy();
    expect(within(lines).getByText('ThreatMate (Included)').closest('tr')).toHaveTextContent('free');
    expect(within(lines).getByText('Managed Services').closest('tr')).not.toHaveTextContent('free');
    expect(within(lines).getByText('Lines total').closest('tr')).toHaveTextContent('$1,000.00');
    expect(screen.queryByTestId('detail-lines-note')).toBeNull();
    expect(within(screen.getByTestId('detail-recurring')).getByText('ThreatMate (Included)').closest('tr')).toHaveTextContent('$37.50');
    const agents = screen.getByTestId('detail-agents');
    expect(within(agents).getByText('Dan Kemp').closest('tr')).toHaveTextContent("this agent's own rate");
    expect(within(agents).getByText('Vic Cio').closest('tr')).toHaveTextContent('the default rate (no rate set for this agent or team)');
    expect(screen.getByTestId('detail-charge-types')).toHaveTextContent('Remote Support 4 h, vCIO 2.5 h');
    expect(screen.getByTestId('detail-tickets')).toHaveTextContent('not sent by CORE yet');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/profitability/client?client_id=5&month=2026-10');
  });

  it('says when the lines do not add up to the revenue, and when there are no lines yet', async () => {
    expect(linesNote(detail({ revenue: 1120.5 }))).toMatch(/lines add up to \$1,000.00.*revenue is \$1,120.50: \$120.50 more than the lines/);
    expect(linesNote(detail({ revenue: 900 }))).toMatch(/\$100.00 less than the lines/);
    expect(linesNote(detail({ revenue: 1000.4 }))).toBe('');
    expect(linesNote(detail({ invoice_lines: [], invoice_lines_total: 0 }))).toMatch(/have not arrived from CORE yet/);
  });

  it('says why when the client was not invoiced that month and closes on request', async () => {
    authFetch.mockImplementation(() => answer({}, 404));
    const onClose = vi.fn();
    render(<ClientProfitDetail clientId="9" month="2026-01" onClose={onClose} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('That client was not invoiced in this month.');
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
