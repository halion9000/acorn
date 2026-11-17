import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const similar = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ alertsApi: { similar } }));

import { SimilarAlertsPanel } from './SimilarAlertsPanel';

const wrap = (id: string) => render(<SWRConfig value={{ provider: () => new Map() }}><SimilarAlertsPanel alertId={id} /></SWRConfig>);

describe('Similar alerts on an alert', () => {
  beforeEach(() => similar.mockReset());

  it('lists each similar alert as a link with its status and the reasons it is alike', async () => {
    similar.mockResolvedValue({ window_days: 30, alerts: [
      { id: 'a/1', title: 'Impossible travel', severity: 'high', status: 'in_progress', created_at: '2026-11-14T10:00:00Z', why: ['same rule', 'same title'] },
      { id: 'a2', title: null, severity: 'low', status: 'new', created_at: null, why: ['same host: pc-1'] },
    ] });
    wrap('x');
    expect(await screen.findByTestId('similar-alerts')).toHaveTextContent('Similar alerts, last 30 days');
    const items = screen.getAllByTestId('similar-alert');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('high · in progress · 2026-11-14');
    expect(items[0]).toHaveTextContent('same rule · same title');
    expect(screen.getByRole('link', { name: 'Impossible travel' })).toHaveAttribute('href', '/alerts/a%2F1');
    expect(items[1]).toHaveTextContent('(untitled)');
    expect(items[1]).toHaveTextContent('same host: pc-1');
    expect(similar).toHaveBeenCalledWith('x');
  });

  it('shows nothing when there are none, or when the answer is not usable', async () => {
    similar.mockResolvedValue({ window_days: 30, alerts: [] });
    const { container, unmount } = wrap('x');
    await vi.waitFor(() => expect(similar).toHaveBeenCalled());
    expect(container.textContent).toBe('');
    unmount();
    similar.mockResolvedValue({});
    const second = wrap('y');
    await vi.waitFor(() => expect(similar).toHaveBeenCalledTimes(2));
    expect(second.container.textContent).toBe('');
  });
});
