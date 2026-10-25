import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { Billing, changeText, clientCsv, totalsCsv } from './Billing';

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/billing/summary'))
      return json({ generated_at: '', days: 30, rows: [{ source: 'cipp', item: 'Microsoft 365 Business Premium', unit: 'licence', clients: 12, total: 310, available: 14, change: 6 }, { source: 'ninjaone', item: 'Macs', unit: 'device', clients: 5, total: 40, available: null, change: null }] });
    if (url.startsWith('/api/v1/mssp/children')) return json([{ id: 'c2', name: 'Beta' }, { id: 'c1', name: 'Acme' }]);
    if (url.startsWith('/api/v1/billing/clients/c1'))
      return json({ client_id: 'c1', days: 30, rows: [{ source: 'ninjaone', item: 'Windows workstations', unit: 'device', count: 13, available: null, change: -2, first_seen_at: '2026-09-01T00:00:00Z', updated_at: '2026-10-25T00:00:00Z' }] });
    if (url.startsWith('/api/v1/billing/changes'))
      return json([{ client_id: 'c1', client_name: 'Acme', source: 'ninjaone', item: 'Windows workstations', unit: 'device', count: 13, previous_count: 15, observed_at: '2026-10-24T00:00:00Z' }, { client_id: 'c2', client_name: 'Beta', source: 'cipp', item: 'Business Basic', unit: 'licence', count: 5, previous_count: null, observed_at: '2026-10-23T00:00:00Z' }]);
    return json({});
  });
});

describe('helpers', () => {
  it('writes a change as plus, minus, no change or a dash', () => {
    expect([changeText(3), changeText(-2), changeText(0), changeText(null), changeText(undefined)]).toEqual(['+3', '-2', 'no change', '—', '—']);
  });
  it('builds a CSV with quoting for commas and quotes, and blanks where there is no number', () => {
    const csv = totalsCsv([{ source: 'cipp', item: 'Business "Premium", annual', unit: 'licence', clients: 2, total: 30, available: null, change: -1 }], 30);
    expect(csv.split('\n')[0]).toBe('Tool,Item,Unit,Clients,Total,Not assigned,Change over 30 days');
    expect(csv.split('\n')[1]).toBe('Microsoft 365 (CIPP),"Business ""Premium"", annual",licence,2,30,,-1');
    expect(clientCsv([{ source: 'ninjaone', item: 'Macs', unit: 'device', count: 4, available: null, change: null, first_seen_at: '', updated_at: '' }], 'Acme', 7).split('\n')[1]).toBe('Acme,NinjaOne,Macs,device,4,,');
  });
});

describe('Billing', () => {
  it('shows each tool\'s total across clients with what is not assigned and the change, and a dash when the change is unknown', async () => {
    render(<Billing />);
    const table = await screen.findByTestId('billing-totals');
    const row = within(table).getByText('Microsoft 365 Business Premium').closest('tr')!;
    expect(within(row).getByText('310')).toBeInTheDocument();
    expect(within(row).getByText('+6')).toBeInTheDocument();
    const macs = within(table).getByText('Macs').closest('tr')!;
    expect(within(macs).getAllByText('—')).toHaveLength(2);
  });

  it('asks again for another comparison date', async () => {
    render(<Billing />);
    await screen.findByTestId('billing-totals');
    await userEvent.selectOptions(screen.getByLabelText('Days'), '90');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('summary?days=90'))).toBe(true));
  });

  it('shows one client\'s counts once picked', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'By client' }));
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');
    const table = await screen.findByTestId('billing-client');
    const row = within(table).getByText('Windows workstations').closest('tr')!;
    expect(within(row).getByText('13')).toBeInTheDocument();
    expect(within(row).getByText('-2')).toBeInTheDocument();
  });

  it('lists the changes with what a count was and is, and new items as new', async () => {
    render(<Billing />);
    await userEvent.click(screen.getByRole('tab', { name: 'Changes' }));
    const table = await screen.findByTestId('billing-changes');
    expect(within(table).getByText('15 → 13')).toBeInTheDocument();
    expect(within(table).getByText('new: 5')).toBeInTheDocument();
  });

  it('says so when nothing has been counted yet', async () => {
    authFetch.mockImplementation(() => json({ generated_at: '', days: 30, rows: [] }));
    render(<Billing />);
    expect(await screen.findByText(/No counts yet/)).toBeInTheDocument();
  });
});
