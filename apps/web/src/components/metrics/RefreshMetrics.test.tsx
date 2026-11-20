import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { RefreshMetrics, refreshLine } from './RefreshMetrics';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('Refresh data on a Metrics page', () => {
  it('says nothing before a press, that CORE was asked, then when newer data arrived', () => {
    const t0 = Date.UTC(2026, 10, 20, 15, 0, 0);
    expect(refreshLine(null, null, t0, false)).toBe('');
    expect(refreshLine(t0, '2026-11-20T14:00:00Z', t0 + 42_000, false)).toMatch(/Asked CORE to read everything again \(42s ago\)/);
    expect(refreshLine(t0, '2026-11-20T15:03:00Z', t0 + 200_000, false)).toMatch(/^Data refreshed at /);
    expect(refreshLine(t0, null, t0 + 1_000_000, true)).toMatch(/has not finished reading yet/);
  });

  it('posts the request, shows Refreshing, reloads every ten seconds until the data is newer, then stops', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    authFetch.mockResolvedValue({ ok: true, status: 202, json: () => Promise.resolve({}) });
    const reload = vi.fn();
    const { rerender } = render(<RefreshMetrics receivedAt="2020-01-01T00:00:00Z" reload={reload} />);
    await userEvent.click(screen.getByRole('button', { name: 'Refresh data' }));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/metrics/refresh', { method: 'POST' });
    expect((await screen.findByRole('button', { name: 'Refreshing…' }) as HTMLButtonElement).disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(10_100);
    expect(reload).toHaveBeenCalledTimes(1);
    rerender(<RefreshMetrics receivedAt={new Date(Date.now() + 60_000).toISOString()} reload={reload} />);
    expect(await screen.findByText(/^Data refreshed at /)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
