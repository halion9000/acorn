import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ noisyRules: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: { noisyRules: api.noisyRules } }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { NoisyRules } from './NoisyRules';

const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <NoisyRules />
    </SWRConfig>,
  );

beforeEach(() => {
  api.noisyRules.mockReset().mockResolvedValue([
    { name: 'Disk space low', source: 'ninjaone', total: 40, open: 5, false_positives: 30, false_positive_rate: 0.75, suggest_hide: true },
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
