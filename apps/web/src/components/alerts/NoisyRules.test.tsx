import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ noisyRules: vi.fn(), hideType: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', () => ({ alertsApi: { noisyRules: api.noisyRules, hideType: api.hideType } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { NoisyRules } from './NoisyRules';

const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <NoisyRules />
    </SWRConfig>,
  );

beforeEach(() => {
  api.hideType.mockReset().mockResolvedValue({ hidden_alerts: 5 });
  api.toast.success.mockReset();
  api.toast.error.mockReset();
  api.noisyRules.mockReset().mockResolvedValue([
    { name: 'Disk space low', source: 'ninjaone', total: 40, open: 5, false_positives: 30, false_positive_rate: 0.75, suggest_hide: true, sample_alert_id: 'alert-1' },
    { name: 'Impossible travel', source: null, total: 12, open: 12, false_positives: 0, false_positive_rate: 0, suggest_hide: false },
  ]);
});

describe('NoisyRules', () => {
  it('lists each rule with its counts and the share that were false positives, and marks only the one worth hiding', async () => {
    show();
    expect(await screen.findByText('Disk space low')).toBeInTheDocument();
    expect(screen.getByText('(75%)')).toBeInTheDocument();
    expect(screen.getAllByText('Worth hiding')).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Disk space low' })).toHaveAttribute('href', '/alerts?status=all&q=Disk%20space%20low');
  });
  it('asks again for the period chosen', async () => {
    show();
    await screen.findByText('Disk space low');
    await userEvent.setup().selectOptions(screen.getByLabelText('Period'), '90');
    await waitFor(() => expect(api.noisyRules).toHaveBeenLastCalledWith(90));
  });
  it('says when there are none, and when it cannot load', async () => {
    api.noisyRules.mockResolvedValueOnce([]);
    const { unmount } = show();
    expect(await screen.findByText('No alerts in this period.')).toBeInTheDocument();
    unmount();
    api.noisyRules.mockRejectedValueOnce(new Error('x'));
    show();
    expect(await screen.findByText('Could not load the report.')).toBeInTheDocument();
  });
});

describe('hiding a noisy rule from the report', () => {
  it('asks first, then hides it for every client for 30 days by its sample alert, and reloads', async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText('Disk space low');
    expect(screen.queryByRole('button', { name: 'Hide Impossible travel' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Hide Disk space low' }));
    expect(api.hideType).not.toHaveBeenCalled();
    expect(screen.getByText(/Hide for every client for 30 days\?/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm hide Disk space low' }));
    await waitFor(() => expect(api.hideType).toHaveBeenCalledWith({ alertId: 'alert-1', scope: 'all', days: 30 }));
    await waitFor(() => expect(api.noisyRules).toHaveBeenCalledTimes(2));
    expect(api.toast.success).toHaveBeenCalledWith(expect.stringContaining('5 open alerts hidden now'));
  });
  it('can be cancelled without hiding anything, and says so when hiding fails', async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText('Disk space low');
    await user.click(screen.getByRole('button', { name: 'Hide Disk space low' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.hideType).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Hide Disk space low' })).toBeInTheDocument();
    api.hideType.mockRejectedValue(new Error('Permission denied: alerts:write'));
    await user.click(screen.getByRole('button', { name: 'Hide Disk space low' }));
    await user.click(screen.getByRole('button', { name: 'Confirm hide Disk space low' }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith('Permission denied: alerts:write'));
  });
  it('offers nothing for a server that sends no sample alert', async () => {
    api.noisyRules.mockResolvedValue([{ name: 'Old', source: null, total: 40, open: 5, false_positives: 30, false_positive_rate: 0.75, suggest_hide: true }]);
    show();
    await screen.findByText('Old');
    expect(screen.queryByRole('button', { name: 'Hide Old' })).toBeNull();
  });
});
