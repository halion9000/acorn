import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ForecastPanel, pointsChange } from './ForecastPanel';

const row = (name: string, now: string, fc: string, m1: number | null, m2: number | null, lines: { item: string; billed: number; counted: number; revenue_change: string }[] = []) => ({
  client_id: name, client_name: name, revenue_now: now, revenue_forecast: fc, revenue_change: String(Number(fc) - Number(now)), cost_now: '0', cost_forecast: '0', margin_percent_now: m1, margin_percent_forecast: m2, changed_lines: lines, lines_without_cost: [],
});
const DATA = {
  received_at: '2026-11-18T00:00:00Z',
  forecast: { clients: [row('Acme', '1000', '900', 60, 55, [{ item: 'Huntress', billed: 10, counted: 8, revenue_change: '-100' }]), row('Birch', '500', '500', 40, 40)], totals: { revenue_now: '1500', revenue_forecast: '1400', revenue_change: '-100', clients_with_changes: 1 } },
};
const ok = (b: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => b });
beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(() => ok(DATA));
});

describe('pointsChange', () => {
  it('says the margin change in points, and nothing when a margin is unknown', () => {
    expect([pointsChange(60, 55), pointsChange(40, 40), pointsChange(40, 42.5), pointsChange(null, 5)]).toEqual(['-5 pts', 'no change', '+2.5 pts', '']);
  });
});

describe('ForecastPanel', () => {
  it('shows each client with revenue now and with the counts, the margin change and the lines that change', async () => {
    render(<ForecastPanel />);
    const table = await screen.findByTestId('forecast-table');
    const acme = within(table).getByText('Acme').closest('tr')!;
    expect(within(acme).getByText('Huntress: 10 to 8')).toBeTruthy();
    expect(within(acme).getByText('-5 pts')).toBeTruthy();
    expect(screen.getByText(/1 clients have lines that would change/)).toBeTruthy();
  });
  it('sorts a column', async () => {
    render(<ForecastPanel />);
    const table = await screen.findByTestId('forecast-table');
    const names = () => within(table).getAllByRole('row').slice(1).map((r) => r.querySelector('td')!.textContent);
    expect(names()).toEqual(['Acme', 'Birch']);
    await userEvent.click(within(table).getByRole('button', { name: /Client/ }));
    await userEvent.click(within(table).getByRole('button', { name: /Client/ }));
    expect(names()).toEqual(['Birch', 'Acme']);
  });
  it('says so when nothing has arrived and explains a refused read', async () => {
    authFetch.mockImplementation(() => ok({ received_at: null, forecast: null }));
    render(<ForecastPanel />);
    expect(await screen.findByText(/has not sent its recurring invoices yet/)).toBeTruthy();
  });
  it('says what permission is missing on a 403', async () => {
    authFetch.mockImplementation(() => Promise.resolve({ ok: false, status: 403, json: async () => ({}) }));
    render(<ForecastPanel />);
    expect(await screen.findByText(/needs both the finance and billing permissions/)).toBeTruthy();
  });
});
