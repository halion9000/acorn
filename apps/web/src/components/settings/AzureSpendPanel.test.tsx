import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const azureSpendApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), azureSpendApi }));
const tenantState = vi.hoisted(() => vi.fn());
vi.mock('@/components/layout/TenantProvider', () => ({ useTenant: () => tenantState() }));

import { AzureSpendPanel, money } from './AzureSpendPanel';

const spend = (over: Record<string, unknown> = {}) => ({
  configured: true, currency: 'USD', month: '2026-10', total: 190.13, forecast: 310, budget: null, fetched_at: '2026-10-31T12:00:00Z', stale: false, error: null,
  by_service: [{ service: 'Virtual Machines', cost: 150.13 }, { service: 'Virtual Network', cost: 40 }],
  daily: [{ date: '2026-10-01', cost: 12 }, { date: '2026-10-02', cost: 8 }], ...over,
});

function renderPanel() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AzureSpendPanel />
    </SWRConfig>,
  );
}

beforeEach(() => {
  azureSpendApi.get.mockReset();
  tenantState.mockReturnValue({ viewingOther: false, home: { name: 'Live Oak IT' } });
  azureSpendApi.get.mockResolvedValue(spend());
});

describe('money', () => {
  it('formats in the currency Azure reports, and falls back for an unknown code', () => {
    expect(money(1234.5, 'USD')).toBe('$1,234.50');
    expect(money(5, 'ZZZZ')).toBe('5.00 ZZZZ');
  });
});

describe('AzureSpendPanel', () => {
  it('while viewing another tenant it offers nothing and asks for no data', async () => {
    tenantState.mockReturnValue({ viewingOther: true, home: { name: 'Live Oak IT' } });
    renderPanel();
    expect(await screen.findByTestId('viewing-other-notice')).toHaveTextContent('Return to Live Oak IT');
    expect(azureSpendApi.get).not.toHaveBeenCalled();
  });

  it('where it is not set up it says so', async () => {
    azureSpendApi.get.mockResolvedValue({ configured: false });
    renderPanel();
    expect(await screen.findByTestId('spend-unconfigured')).toHaveTextContent('Not set up');
  });

  it('shows the month so far, the projection, each service and a bar per day, and no budget when none is set', async () => {
    renderPanel();
    expect(await screen.findByTestId('spend-total')).toHaveTextContent('$190.13');
    expect(screen.getByTestId('spend-forecast')).toHaveTextContent('$310.00');
    expect(screen.getByText('Virtual Machines')).toBeInTheDocument();
    expect(screen.getAllByTestId('spend-day')).toHaveLength(2);
    expect(screen.queryByTestId('spend-budget')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('shows a budget bar only when a budget is set', async () => {
    azureSpendApi.get.mockResolvedValue(spend({ budget: 500 }));
    renderPanel();
    expect(await screen.findByTestId('spend-budget')).toHaveTextContent('$500.00');
    expect(screen.getByRole('progressbar', { name: 'Budget used' })).toHaveAttribute('aria-valuenow', '38');
  });

  it('says plainly when Azure has posted nothing yet, instead of showing zeros as data', async () => {
    azureSpendApi.get.mockResolvedValue(spend({ total: 0, forecast: null, by_service: [], daily: [] }));
    renderPanel();
    expect(await screen.findByTestId('spend-empty')).toHaveTextContent('not posted any charges');
    expect(screen.getByTestId('spend-forecast')).toHaveTextContent('Not enough data yet');
  });

  it('shows the reason a read failed, and that the numbers are the last good ones', async () => {
    azureSpendApi.get.mockResolvedValue(spend({ stale: true, error: 'Azure is rate-limiting cost requests.' }));
    renderPanel();
    expect(await screen.findByTestId('spend-error')).toHaveTextContent('rate-limiting cost requests. Showing the last answer.');
    expect(screen.getByTestId('spend-total')).toHaveTextContent('$190.13');
  });

  it('Refresh asks the server to read again', async () => {
    renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Refresh' }));
    expect(azureSpendApi.get).toHaveBeenLastCalledWith(true);
  });
});
