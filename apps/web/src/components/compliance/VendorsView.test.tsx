import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const vendorApi = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), archive: vi.fn(), restore: vi.fn(), startReview: vi.fn(), completeReview: vi.fn(), addDocument: vi.fn(), removeDocument: vi.fn() }));
const detected = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), vendorApi, detectedAppsApi: detected, msspApi: { listChildren: async () => [] } }));

import { VendorsView } from './VendorsView';

const vendor = (over: Record<string, unknown> = {}) => ({
  id: 'v1', name: 'LastPass', website: null, trust_url: null, service: 'Password manager', category: 'Security tools', owner: 'Hal', risk_level: 'high', data_access: 'sensitive',
  auth_type: null, mfa: true, account_manager_name: null, account_manager_email: null, contract_start: null, contract_end: null, review_interval_months: 12, notes: '', status: 'active',
  review_state: 'due', next_review_due: '2026-12-01', last_reviewed: null, document_count: 0, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', archived_at: null, ...over,
});
const lists = (vendors = [vendor()]) => ({
  vendors, summary: { total: vendors.length, by_risk: { high: vendors.length, critical: 0, medium: 0, low: 0, unassessed: 0 }, reviews_overdue: 0, reviews_in_progress: 0, unassessed: 0 },
  categories: ['Security tools', 'Other'], document_types: ['Contract', 'Other'],
});
const detail = (over: Record<string, unknown> = {}) => ({ ...vendor(), applications: [], reviews: [], documents: [], history: [], ...over });
const waitingApps = (n: number) => ({ apps: [], counts: { new: n, added: 0, linked: 0, ignored: 0 }, vendors: [] });

beforeEach(() => {
  Object.values(vendorApi).forEach((m) => m.mockReset());
  detected.list.mockReset();
  vendorApi.list.mockResolvedValue(lists());
  vendorApi.get.mockResolvedValue(detail());
  detected.list.mockResolvedValue(waitingApps(0));
  window.history.replaceState(null, '', '/compliance/vendors');
});

describe('VendorsView', () => {
  it('shows the counts by risk level on the dashboard and the vendors on the register', async () => {
    render(<VendorsView />);
    expect(await screen.findByTestId('vcount-high')).toHaveTextContent('1');
    await userEvent.click(screen.getByRole('tab', { name: 'register' }));
    const table = await screen.findByTestId('vendor-table');
    expect(table).toHaveTextContent('LastPass');
    expect(table).toHaveTextContent('Review due soon');
  });

  it('a banner says how many detected applications are waiting and links to them for the client in the address', async () => {
    detected.list.mockResolvedValue(waitingApps(49));
    window.history.replaceState(null, '', '/compliance/vendors?client=c9');
    render(<VendorsView />);
    const banner = await screen.findByTestId('detected-banner');
    expect(banner).toHaveTextContent('49 new applications detected.');
    expect(banner.querySelector('a')).toHaveAttribute('href', '/compliance/vendors/detected?client=c9');
  });

  it('no banner when nothing is waiting', async () => {
    render(<VendorsView />);
    await screen.findByTestId('vcount-high');
    expect(screen.queryByTestId('detected-banner')).toBeNull();
  });

  it('no banner when an older server cannot say', async () => {
    detected.list.mockRejectedValue(new Error('404'));
    render(<VendorsView />);
    await screen.findByTestId('vcount-high');
    expect(screen.queryByTestId('detected-banner')).toBeNull();
  });

  it('a vendor with linked applications shows them with their accounts added up', async () => {
    vendorApi.get.mockResolvedValue(
      detail({
        applications: [
          { id: 'a1', name: 'LastPass Login App', source_label: 'Microsoft 365', accounts: 47, risky: false, first_seen: '2026-06-02T10:00:00Z' },
          { id: 'a2', name: 'LastPass Provisioning App', source_label: 'Microsoft 365', accounts: 47, risky: true, first_seen: '2026-06-02T10:00:00Z' },
        ],
      }),
    );
    render(<VendorsView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'register' }));
    await userEvent.click(await screen.findByRole('button', { name: 'LastPass' }));
    const box = await screen.findByTestId('vendor-applications');
    expect(box).toHaveTextContent('2 apps, 94 accounts in all');
    expect(box).toHaveTextContent('holds a risky permission');
  });

  it('adds a vendor and opens it', async () => {
    vendorApi.create.mockResolvedValue(detail({ name: 'Zoom', id: 'v2' }));
    render(<VendorsView />);
    await screen.findByTestId('vcount-high');
    await userEvent.click(screen.getByRole('button', { name: 'Add vendor' }));
    await userEvent.type(await screen.findByLabelText('Vendor name'), 'Zoom');
    await userEvent.click(screen.getByRole('button', { name: 'Save vendor' }));
    await waitFor(() => expect(vendorApi.create).toHaveBeenCalledWith('', expect.objectContaining({ name: 'Zoom', risk_level: 'unassessed' })));
    expect(await screen.findByTestId('vendor-detail')).toHaveTextContent('Zoom');
  });
});
