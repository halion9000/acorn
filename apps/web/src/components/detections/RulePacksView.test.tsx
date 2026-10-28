import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';
import type { ManagedTenantRow, RulePackOverview } from '@/lib/api';

const api = vi.hoisted(() => ({ rulePacks: vi.fn(), tenants: vi.fn(), setRulePackForClient: vi.fn() }));
vi.mock('@/lib/api', () => ({ msspApi: api }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import toast from 'react-hot-toast';
import { RulePacksView, matchingClients } from './RulePacksView';

const client = (name: string): ManagedTenantRow => ({ tenant_id: `id-${name}`, name, has_metrics: false, snapshot_at: null, health_score: null, open_alerts: null, critical_alerts: null, open_cases: null, mttr_minutes: null, sla_breaches: null, connector_count: null });
const windows: RulePackOverview = {
  id: 'p-win',
  name: 'Sigma: Windows',
  description: 'Rules for Windows.',
  category: 'sigma',
  rules: [
    { id: 'r1', name: 'Zerologon exploitation', severity: 'critical', category: 'endpoint' },
    { id: 'r2', name: 'UAC disabled', severity: 'medium', category: 'endpoint' },
  ],
  applied_to: ['id-Acme'],
};
const linux: RulePackOverview = { id: 'p-lin', name: 'Sigma: Linux', description: null, category: 'sigma', rules: [], applied_to: [] };

function show() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <RulePacksView />
    </SWRConfig>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.rulePacks.mockResolvedValue([windows, linux]);
  api.tenants.mockResolvedValue([client('Birch'), client('Acme')]);
  api.setRulePackForClient.mockResolvedValue(undefined);
  vi.mocked(toast.error).mockReset();
});

describe('matchingClients', () => {
  it('filters by name ignoring case and sorts by name', () => {
    expect(matchingClients([client('Birch Law'), client('acme dental'), client('Cedar')], '').map((c) => c.name)).toEqual(['acme dental', 'Birch Law', 'Cedar']);
    expect(matchingClients([client('Birch Law'), client('acme dental')], '  LAW ').map((c) => c.name)).toEqual(['Birch Law']);
  });
});

describe('the rule packs tab', () => {
  it('lists each pack with how many clients it is applied to, and its rules on request', async () => {
    const user = userEvent.setup();
    show();
    const pack = await screen.findByRole('region', { name: 'Sigma: Windows' });
    expect(within(pack).getByTestId('pack-applied')).toHaveTextContent('Applied to 1 of 2 clients');
    expect(within(screen.getByRole('region', { name: 'Sigma: Linux' })).getByTestId('pack-applied')).toHaveTextContent('Applied to 0 of 2 clients');
    expect(within(pack).queryByText('Zerologon exploitation')).toBeNull();
    await user.click(within(pack).getByRole('button', { name: /Show the 2 rules/ }));
    expect(within(pack).getByText('Zerologon exploitation')).toBeInTheDocument();
    expect(within(pack).getByText('critical')).toBeInTheDocument();
  });

  it('ticks a client for a pack, saves it, and updates the count at once', async () => {
    const user = userEvent.setup();
    show();
    const pack = await screen.findByRole('region', { name: 'Sigma: Windows' });
    await user.click(within(pack).getByRole('button', { name: 'Choose clients' }));
    const birch = within(pack).getByRole('checkbox', { name: 'Apply Sigma: Windows to Birch' });
    expect(within(pack).getByRole('checkbox', { name: 'Apply Sigma: Windows to Acme' })).toBeChecked();
    expect(birch).not.toBeChecked();
    await user.click(birch);
    expect(api.setRulePackForClient).toHaveBeenCalledWith('p-win', 'id-Birch', true);
    expect(birch).toBeChecked();
    expect(within(pack).getByTestId('pack-applied')).toHaveTextContent('Applied to 2 of 2 clients');
    await user.click(within(pack).getByRole('checkbox', { name: 'Apply Sigma: Windows to Acme' }));
    expect(api.setRulePackForClient).toHaveBeenCalledWith('p-win', 'id-Acme', false);
    expect(within(pack).getByTestId('pack-applied')).toHaveTextContent('Applied to 1 of 2 clients');
  });

  it('puts the tick back and says why when the change cannot be saved', async () => {
    api.setRulePackForClient.mockRejectedValue(new Error('Permission denied: mssp:manage'));
    const user = userEvent.setup();
    show();
    const pack = await screen.findByRole('region', { name: 'Sigma: Windows' });
    await user.click(within(pack).getByRole('button', { name: 'Choose clients' }));
    const birch = within(pack).getByRole('checkbox', { name: 'Apply Sigma: Windows to Birch' });
    await user.click(birch);
    await waitFor(() => expect(birch).not.toBeChecked());
    expect(toast.error).toHaveBeenCalledWith('Permission denied: mssp:manage');
    expect(within(pack).getByTestId('pack-applied')).toHaveTextContent('Applied to 1 of 2 clients');
  });

  it('narrows the client list with the search box', async () => {
    const user = userEvent.setup();
    show();
    const pack = await screen.findByRole('region', { name: 'Sigma: Windows' });
    await user.click(within(pack).getByRole('button', { name: 'Choose clients' }));
    await user.type(within(pack).getByRole('searchbox', { name: /Search clients/ }), 'bir');
    expect(within(pack).queryByRole('checkbox', { name: /Acme/ })).toBeNull();
    expect(within(pack).getByRole('checkbox', { name: /Birch/ })).toBeInTheDocument();
  });

  it('says so when there are no packs, and when they cannot be loaded', async () => {
    api.rulePacks.mockResolvedValue([]);
    const first = show();
    expect(await screen.findByText('No rule packs yet')).toBeInTheDocument();
    first.unmount();
    api.rulePacks.mockRejectedValue(new Error('503'));
    show();
    expect(await screen.findByText("Couldn't load rule packs")).toBeInTheDocument();
  });
});
