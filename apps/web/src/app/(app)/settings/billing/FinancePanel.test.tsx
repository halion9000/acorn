import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { FinancePanel } from './FinancePanel';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

const margin = {
  clients: [
    { client_id: 'b', client_name: 'Beta', revenue: '18.00', cost: '10.50', margin: '7.50', margin_percent: 41.7, unpriced_items: ['Mystery line'] },
    { client_id: 'a', client_name: 'Acme', revenue: '180.00', cost: '123.00', margin: '57.00', margin_percent: 31.7, unpriced_items: [] },
  ],
  totals: { revenue: '198.00', cost: '133.50', margin: '64.50', margin_percent: 32.6 },
  priced_items: 1,
  note: 'An estimate: only lines with both a price and a cost are counted.',
};

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/finance/margin') return json(margin);
    if (url === '/api/v1/finance/prices' && init?.method === 'PUT') return json({});
    if (url === '/api/v1/finance/prices') return json({ prices: [{ invoice_item: 'Huntress per endpoint', unit_price: '6.00', unit_cost: '3.50' }], billed_items: ['Huntress per endpoint', 'Mystery line'] });
    return json({}, 404);
  });
});

describe('FinancePanel', () => {
  it('shows each client revenue, cost, margin and what is not priced, with the total, and the estimate note', async () => {
    render(<FinancePanel />);
    const row = await screen.findByTestId('margin-Acme');
    expect(row).toHaveTextContent('180.00');
    expect(row).toHaveTextContent('57.00');
    expect(row).toHaveTextContent('31.7%');
    expect(screen.getByTestId('margin-Beta')).toHaveTextContent('Mystery line');
    expect(screen.getByTestId('margin-total')).toHaveTextContent('64.50');
    expect(screen.getByTestId('finance')).toHaveTextContent('An estimate');
    expect(screen.getByTestId('finance-unpriced')).toHaveTextContent('Mystery line');
  });

  it('saves a price as text so no money passes through a float, then reloads', async () => {
    const user = userEvent.setup();
    render(<FinancePanel />);
    await screen.findByTestId('finance');
    await user.type(screen.getByLabelText('Invoice line'), 'Mystery line');
    await user.type(screen.getByLabelText('Price per unit'), '12.50');
    await user.type(screen.getByLabelText('Cost per unit'), '8');
    await user.click(screen.getByRole('button', { name: 'Save price' }));
    await waitFor(() => {
      const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT');
      expect(JSON.parse(put![1].body)).toEqual({ invoice_item: 'Mystery line', unit_price: '12.50', unit_cost: '8' });
    });
  });

  it('shows no money to someone without the finance permission', async () => {
    authFetch.mockImplementation(() => json({ detail: 'forbidden' }, 403));
    render(<FinancePanel />);
    expect(await screen.findByTestId('finance-denied')).toHaveTextContent('finance permission');
    expect(screen.queryByTestId('finance')).toBeNull();
  });
});
