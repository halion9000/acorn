import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { LoginAbusePanel, isLoginAbuse } from './LoginAbusePanel';

const body = (over: Record<string, unknown> = {}) => ({ window_minutes: 15, failures: 12, addresses_tried: 3, clients: 2, locked_addresses: 0, locked_clients: 0, busiest_clients: [{ client: '203.0.113.x', failures: 9 }], ...over });
const answer = (b: unknown, ok = true) => authFetch.mockResolvedValue({ ok, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
});

describe('LoginAbusePanel', () => {
  it('says how many failed, from how many places, and the busiest masked clients', async () => {
    answer(body());
    render(<LoginAbusePanel />);
    const box = await screen.findByTestId('login-abuse');
    expect(box).toHaveTextContent('Failed sign-ins in the last 15 minutes: 12 from 2 places against 3 addresses.');
    expect(box).toHaveTextContent('Busiest: 203.0.113.x (9)');
    expect(box).not.toHaveTextContent('locked now');
  });
  it('says what is locked now, in amber', async () => {
    answer(body({ locked_addresses: 1, locked_clients: 2 }));
    render(<LoginAbusePanel />);
    const box = await screen.findByTestId('login-abuse');
    expect(box).toHaveTextContent('locked now: 1 address, 2 places');
    expect(box.querySelector('p')).toHaveClass('text-amber-300');
  });
  it('shows nothing when the read is refused, fails, or the answer is not this view', async () => {
    answer({}, false);
    const a = render(<LoginAbusePanel />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('login-abuse')).toBeNull();
    a.unmount();
    answer({ overall: 'ok', down: [], services: [] });
    const b = render(<LoginAbusePanel />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('login-abuse')).toBeNull();
    b.unmount();
    authFetch.mockRejectedValueOnce(new Error('down'));
    render(<LoginAbusePanel />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(3));
    expect(screen.queryByTestId('login-abuse')).toBeNull();
  });
  it('recognises only the real shape', () => {
    expect(isLoginAbuse(body())).toBe(true);
    expect(isLoginAbuse(null)).toBe(false);
    expect(isLoginAbuse({ failures: 1 })).toBe(false);
  });
});
