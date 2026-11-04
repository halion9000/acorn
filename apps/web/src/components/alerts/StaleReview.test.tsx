import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ staleSummary: vi.fn(), restoreStale: vi.fn(), closeStale: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: { staleSummary: api.staleSummary, restoreStale: api.restoreStale, closeStale: api.closeStale } }));

import { StaleReview } from './StaleReview';

const show = (clientId?: string, onChanged = vi.fn()) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <StaleReview clientId={clientId} onChanged={onChanged} />
    </SWRConfig>,
  );

beforeEach(() => {
  api.staleSummary.mockReset().mockResolvedValue({ days: 30, exempt_severities: ['critical', 'high'], total: 12, by_client: [], by_severity: { low: 12 } });
  api.restoreStale.mockReset().mockResolvedValue({ changed: 12 });
  api.closeStale.mockReset().mockResolvedValue({ changed: 12 });
});

describe('StaleReview', () => {
  it('says how many there are, why, and that nothing is deleted', async () => {
    show();
    expect(await screen.findByText(/12 stale alerts/)).toBeInTheDocument();
    expect(screen.getByText(/after 30 days with no activity/)).toBeInTheDocument();
    expect(screen.getByText(/Critical and high alerts \(critical, high\)/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is deleted/)).toBeInTheDocument();
  });
  it('asks first, and does nothing on No', async () => {
    show();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Close all' }));
    expect(screen.getByRole('dialog', { name: 'Are you sure?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(api.closeStale).not.toHaveBeenCalled();
    expect(api.restoreStale).not.toHaveBeenCalled();
  });
  it('puts them all back for the picked client only, and tells the list to refresh', async () => {
    const onChanged = vi.fn();
    show('c1', onChanged);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Put all back' }));
    await user.click(screen.getByRole('button', { name: 'Yes, put them back' }));
    await waitFor(() => expect(api.restoreStale).toHaveBeenCalledWith({ client_id: 'c1', confirm: true }));
    expect(await screen.findByText('12 alerts put back.')).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });
  it('closes for every client when none is picked, and shows a refusal in the window', async () => {
    api.closeStale.mockRejectedValue(new Error('Not allowed.'));
    show();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Close all' }));
    await user.click(screen.getByRole('button', { name: 'Yes, close them' }));
    expect(await screen.findByText('Not allowed.')).toBeInTheDocument();
    expect(api.closeStale).toHaveBeenCalledWith({ confirm: true });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
  it('offers nothing to act on when there are none', async () => {
    api.staleSummary.mockResolvedValue({ days: 30, exempt_severities: [], total: 0, by_client: [], by_severity: {} });
    show();
    expect(await screen.findByText(/0 stale alerts/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close all' })).toBeDisabled();
  });
});
