import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { SecureframeCard, failingDays, type SecureframeView } from './SecureframeCard';

const VIEW: SecureframeView = {
  report: {
    tests: { total: 10, enabled: 8, passing: 5, failing: 2, not_evaluated: 1, disabled: 2 },
    frameworks: [
      { key: 'soc2', name: 'SOC 2', failing: 2, passing: 5 },
      { key: 'iso27001', name: null, failing: 0, passing: 3 },
    ],
    failing: [{ key: 't1', title: 'MFA on all accounts', owner: 'Dale', failing_since: '2026-10-01T00:00:00Z', frameworks: ['soc2'], domain: null, message: null }],
    risks: 12,
    policies: null,
  },
  received_at: '2026-10-29T12:00:00Z',
  passing_percent: 71.4,
};

const view = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <SecureframeCard />
    </SWRConfig>,
  );

beforeEach(() => authFetch.mockReset());
afterEach(() => cleanup());

describe('failingDays', () => {
  it('counts whole days, never negative, and is null when unknown', () => {
    const now = Date.parse('2026-10-29T12:00:00Z');
    expect(failingDays('2026-10-01T00:00:00Z', now)).toBe(28);
    expect(failingDays('2026-11-01T00:00:00Z', now)).toBe(0);
    expect(failingDays(null, now)).toBeNull();
    expect(failingDays('not a date', now)).toBeNull();
  });
});

describe('SecureframeCard', () => {
  it('shows the pass share, the framework tallies and the tests failing longest with owner and age', async () => {
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(VIEW) });
    view();
    const card = await screen.findByTestId('secureframe-card');
    expect(card).toHaveTextContent('71.4% of evaluated tests pass: 5 passing, 2 failing, 1 not evaluated, 2 disabled.');
    expect(card).toHaveTextContent('12 risks.');
    expect(card).not.toHaveTextContent('policies');
    expect(screen.getByRole('progressbar', { name: 'Secureframe tests passing' })).toHaveAttribute('aria-valuenow', '71');
    expect(screen.getByTestId('secureframe-frameworks')).toHaveTextContent('SOC 2: 2 failing of 7');
    expect(screen.getByTestId('secureframe-frameworks')).toHaveTextContent('iso27001: 0 failing of 3');
    expect(screen.getByTestId('secureframe-failing')).toHaveTextContent('MFA on all accounts · Dale · failing');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/secureframe');
  });

  it('shows nothing when Secureframe has not reported, or the read fails', async () => {
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ report: null, received_at: null, passing_percent: null }) });
    const first = view();
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('secureframe-card')).toBeNull();
    first.unmount();
    authFetch.mockResolvedValue({ ok: false, status: 403, json: () => Promise.resolve({}) });
    view();
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('secureframe-card')).toBeNull();
  });
});
