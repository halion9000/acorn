import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ProfitTrend, breakdownRow, whole, type TrendData } from './ProfitTrend';

const DATA: TrendData = {
  received_at: 'x',
  months: ['2026-09', '2026-10'],
  series: [
    { month: '2026-09', revenue: '900.00', labor: '650.00', after_labor: '250.00', margin_percent: 27.8, hours: '10.00', clients_invoiced: 1 },
    { month: '2026-10', revenue: '1400.50', labor: '700.00', after_labor: '700.50', margin_percent: 50, hours: '10.50', clients_invoiced: 2 },
  ],
  clients: [
    { client_id: '5', client_name: 'Acme Dental, Inc.', revenue: '1900', by_month: { '2026-09': { revenue: '900', labor: '650', after_labor: '250' }, '2026-10': { revenue: '1000', labor: '635', after_labor: '365' } } },
    { client_id: '6', client_name: 'Birch Law', revenue: '400.5', by_month: { '2026-10': { revenue: '400.5', labor: '65', after_labor: '335.5' } } },
  ],
  clients_left_out: 3,
};

afterEach(() => cleanup());

describe('the profitability trend', () => {
  it('rounds amounts sent as text', () => {
    expect([whole('900.40'), whole(700.5), whole('x')]).toEqual([900, 701, 0]);
  });

  it('builds a client row of profit by month, a dash for a month with no invoice, and the margin over the period', () => {
    expect(breakdownRow(DATA.clients[0]!, DATA.months)).toEqual(['Acme Dental, Inc.', '$250', '$365', '$615', '32.4%']);
    expect(breakdownRow(DATA.clients[1]!, DATA.months)).toEqual(['Birch Law', '—', '$336', '$336', '83.8%']);
  });

  it('shows the three charts and the breakdown for the months asked', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(DATA) });
    render(<ProfitTrend months={12} />);
    const trend = await screen.findByTestId('profit-trend');
    expect(within(trend).getByText('Revenue vs labor by month')).toBeInTheDocument();
    expect(within(screen.getByTestId('trend-clients')).getByText('Oct 26')).toBeInTheDocument();
    expect(within(screen.getByTestId('trend-breakdown')).getByText('Birch Law')).toBeInTheDocument();
    expect(within(screen.getByTestId('trend-breakdown')).getByText('The 3 smallest clients are not shown.')).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/profitability/trend?months=12');
  });

  it('shows nothing until CORE has sent the summary', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: null, months: [], series: [], clients: [] }) });
    const { container } = render(<ProfitTrend />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.textContent).toBe('');
  });
});
