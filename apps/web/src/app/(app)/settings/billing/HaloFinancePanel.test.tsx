import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { HaloFinancePanel, receivedText } from './HaloFinancePanel';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

const buckets = (over: Record<string, string> = {}) => ({ not_due: '0.00', '1_30': '0.00', '31_60': '0.00', '61_90': '0.00', over_90: '0.00', ...over });
const data = {
  received_at: '2026-11-13T14:02:11Z',
  margin: {
    clients: [
      { client_id: '30', client_name: 'Birch Law', recurring_invoices: 1, revenue: '125.00', costed_revenue: '125.00', cost: '100.00', margin: '25.00', margin_percent: 20, lines_without_cost: [] },
      { client_id: '12', client_name: 'Acme Dental', recurring_invoices: 2, revenue: '392.00', costed_revenue: '312.00', cost: '115.00', margin: '197.00', margin_percent: 63.1, lines_without_cost: ['Backup'] },
    ],
    totals: { revenue: '517.00', costed_revenue: '437.00', cost: '215.00', margin: '222.00', margin_percent: 50.8 },
  },
  aging: {
    clients: [
      { client_id: '12', client_name: 'Acme Dental', owed: '600.25', buckets: buckets({ '1_30': '100.25', over_90: '500.00' }), invoices: [{ number: 'INV-1', due: '2026-08-01', days_late: 104, amount_due: '500.00', bucket: 'over_90' }, { number: 'INV-2', due: '2026-11-01', days_late: 12, amount_due: '100.25', bucket: '1_30' }] },
    ],
    totals: { ...buckets({ '1_30': '100.25', over_90: '500.00' }), owed: '600.25' },
    labels: { not_due: 'Not yet due', '1_30': '1-30 days late', '31_60': '31-60 days late', '61_90': '61-90 days late', over_90: 'Over 90 days late' },
  },
};

beforeEach(() => authFetch.mockReset());

describe('HaloFinancePanel', () => {
  it('says when CORE last sent the snapshot, or that it has not sent one', () => {
    expect(receivedText('2026-11-13T14:02:11Z')).toBe("From HaloPSA, as CORE last read it: 2026-11-13 14:02 UTC.");
    expect(receivedText(null)).toMatch(/has not sent HaloPSA/);
  });

  it('shows margin per client with the lines that have no cost named, and the total', async () => {
    authFetch.mockImplementation(() => json(data));
    render(<HaloFinancePanel />);
    const acme = await screen.findByTestId('halo-margin-Acme Dental');
    expect(acme).toHaveTextContent('197.00');
    expect(acme).toHaveTextContent('63.1%');
    expect(acme).toHaveTextContent('Backup');
    expect(screen.getByTestId('halo-margin-total')).toHaveTextContent('222.00');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/finance/halo');
  });

  it('shows what is owed by lateness, and a client press lists its invoices with how late each is', async () => {
    authFetch.mockImplementation(() => json(data));
    render(<HaloFinancePanel />);
    const row = await screen.findByTestId('aging-Acme Dental');
    expect(row).toHaveTextContent('500.00');
    expect(row).toHaveTextContent('600.25');
    expect(screen.getByTestId('aging-total')).toHaveTextContent('600.25');
    expect(screen.queryByTestId('aging-invoices-Acme Dental')).toBeNull();
    await userEvent.click(row);
    const list = screen.getByTestId('aging-invoices-Acme Dental');
    expect(within(list).getByText(/INV-1 · 500.00 · due 2026-08-01, 104 days late/)).toBeTruthy();
  });

  it('before any snapshot it says so and shows no tables; without the finance permission it shows nothing at all', async () => {
    authFetch.mockImplementation(() => json({ received_at: null, margin: null, aging: null }));
    const { unmount } = render(<HaloFinancePanel />);
    expect(await screen.findByTestId('halo-finance-received')).toHaveTextContent(/has not sent HaloPSA/);
    expect(screen.queryByTestId('halo-margin-total')).toBeNull();
    unmount();
    authFetch.mockImplementation(() => json({ detail: 'no' }, 403));
    const denied = render(<HaloFinancePanel />);
    await Promise.resolve();
    expect(denied.container.textContent).toBe('');
  });
});
