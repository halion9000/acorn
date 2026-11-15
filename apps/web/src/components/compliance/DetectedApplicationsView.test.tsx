import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), link: vi.fn(), ignore: vi.fn(), restore: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), detectedAppsApi: api, msspApi: { listChildren: async () => [] } }));

import { DetectedApplicationsView } from './DetectedApplicationsView';

const app = (over: Record<string, unknown> = {}) => ({
  id: 'a1', name: 'LastPass Login App', source: 'cipp', source_label: 'Microsoft 365', accounts: 47, scopes: ['User.Read'], risky: false,
  first_seen: '2026-06-02T10:00:00Z', last_seen: '2026-11-14T10:00:00Z', status: 'new', vendor_id: null, vendor_name: null, ...over,
});
const list = (apps = [app()], over: Record<string, unknown> = {}) => ({ apps, counts: { new: apps.filter((a) => a.status === 'new').length, added: 0, linked: 0, ignored: 0 }, vendors: [{ id: 'v1', name: 'LastPass' }], ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue(list());
  api.add.mockResolvedValue(app({ status: 'added' }));
  api.link.mockResolvedValue(app({ status: 'linked' }));
  api.ignore.mockResolvedValue(app({ status: 'ignored' }));
  api.restore.mockResolvedValue(app());
  window.history.replaceState(null, '', '/compliance/vendors/detected');
});

describe('DetectedApplicationsView', () => {
  it('lists what is waiting with its date, source and accounts, and flags a risky permission', async () => {
    api.list.mockResolvedValue(list([app(), app({ id: 'a2', name: 'Mail Sync', accounts: 3, risky: true })]));
    render(<DetectedApplicationsView />);
    const rows = await screen.findAllByTestId('detected-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('LastPass Login App');
    expect(rows[0]).toHaveTextContent('2026-06-02');
    expect(rows[0]).toHaveTextContent('Microsoft 365');
    expect(rows[0]).toHaveTextContent('47');
    expect(rows[1]).toHaveTextContent('risky permission');
    expect(screen.getByRole('tab', { name: 'To review (2)' })).toBeTruthy();
  });

  it('Add, Ignore and Link each ask the server and reload the list', async () => {
    render(<DetectedApplicationsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add LastPass Login App' }));
    await waitFor(() => expect(api.add).toHaveBeenCalledWith('', 'a1'));
    await userEvent.click(await screen.findByRole('button', { name: 'Ignore LastPass Login App' }));
    await waitFor(() => expect(api.ignore).toHaveBeenCalledWith('', 'a1'));
    await userEvent.click(await screen.findByRole('button', { name: 'Link LastPass Login App' }));
    expect((screen.getByRole('button', { name: 'Link it' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('Vendor to link LastPass Login App to'), 'v1');
    await userEvent.click(screen.getByRole('button', { name: 'Link it' }));
    await waitFor(() => expect(api.link).toHaveBeenCalledWith('', 'a1', 'v1'));
    expect(api.list.mock.calls.length).toBeGreaterThanOrEqual(4);
  });

  it('an ignored app can be brought back, and the client in the address is the one asked about', async () => {
    window.history.replaceState(null, '', '/compliance/vendors/detected?client=c9');
    api.list.mockResolvedValue(list([app({ status: 'ignored' })], { counts: { new: 0, added: 0, linked: 0, ignored: 1 } }));
    render(<DetectedApplicationsView />);
    await waitFor(() => expect(api.list).toHaveBeenCalledWith('c9', 'new'));
    await userEvent.click(screen.getByRole('tab', { name: 'Ignored' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Bring back LastPass Login App' }));
    await waitFor(() => expect(api.restore).toHaveBeenCalledWith('c9', 'a1'));
  });

  it('pages ten at a time, and says so when nothing is waiting', async () => {
    api.list.mockResolvedValue(list(Array.from({ length: 12 }, (_, i) => app({ id: `x${i}`, name: `App ${i}` }))));
    render(<DetectedApplicationsView />);
    expect(await screen.findAllByTestId('detected-row')).toHaveLength(10);
    expect(screen.getByTestId('detected-pager')).toHaveTextContent('1 - 10 of 12 items');
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getAllByTestId('detected-row')).toHaveLength(2);
    api.list.mockResolvedValue(list([]));
    await userEvent.click(screen.getByRole('tab', { name: 'Ignored' }));
    expect(await screen.findByTestId('detected-empty')).toBeTruthy();
  });

  it('shows the reason when the list cannot be loaded', async () => {
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<DetectedApplicationsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});
