import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { LicensingApps, appPercent } from './LicensingApps';

const REPORT = {
  received_at: '2026-11-20T00:00:00Z',
  months: ['2026-10', '2026-09'],
  month: '2026-10',
  apps: [
    { app: 'Huntress EDR', clients: 3, common: true },
    { app: 'NinjaOne RMM', clients: 3, common: true },
    { app: 'Rare App', clients: 1, common: false },
  ],
  clients: [
    { client: 'Acme', apps: ['Huntress EDR', 'NinjaOne RMM', 'Rare App'] },
    { client: 'Birch', apps: ['Huntress EDR'] },
  ],
};

afterEach(() => cleanup());

describe('the billed apps', () => {
  it('works out the share of the common apps a client has', () => {
    expect(appPercent(['A', 'B', 'X'], ['A', 'B'])).toBe(100);
    expect(appPercent(['A'], ['A', 'B', 'C'])).toBe(33);
    expect(appPercent(['A'], [])).toBe(0);
  });

  it('shows the common apps to start with, a check or a dash for each client, the percentage and the total', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<LicensingApps />);
    const table = await screen.findByTestId('licensing-apps-table');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Client Name', 'Percentage', 'Huntress EDR', 'NinjaOne RMM', 'Total Apps']);
    const acme = within(table).getByText('Acme').closest('tr')!;
    expect([...acme.querySelectorAll('td')].map((c) => c.textContent)).toEqual(['Acme', '100%', '✓', '✓', '2']);
    const birch = within(table).getByText('Birch').closest('tr')!;
    expect([...birch.querySelectorAll('td')].map((c) => c.textContent)).toEqual(['Birch', '50%', '✓', '–', '1']);
  });

  it('asks for the month chosen, lets a rare app be added, and says so when no client is chosen', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<LicensingApps />);
    await screen.findByTestId('licensing-apps-table');
    await userEvent.selectOptions(screen.getByLabelText('Billed month'), '2026-09');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/metrics/licensing-apps?month=2026-09'));
    await userEvent.click(screen.getByRole('button', { name: /software/ }));
    await userEvent.click(screen.getByLabelText(/Rare App/));
    expect(within(screen.getByTestId('licensing-apps-table')).getByText('Rare App')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /clients/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('No clients selected')).toBeInTheDocument();
  });

  it('says nothing has arrived when CORE has sent no invoice lines', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: null, months: [], month: null, apps: [], clients: [] }) });
    render(<LicensingApps />);
    expect(await screen.findByTestId('nothing-yet')).toBeInTheDocument();
  });
});
