import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { SigninHistoryCard, addressesNote, signinTime } from './SigninHistoryCard';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><SigninHistoryCard /></SWRConfig>);

beforeEach(() => {
  authFetch.mockReset();
});

describe('signinTime and addressesNote', () => {
  it('gives the minute in UTC, and says so when there is no time or it cannot be read', () => {
    expect(signinTime('2026-11-10T09:30:45+00:00')).toBe('2026-11-10 09:30 UTC');
    expect(signinTime(null)).toBe('time not recorded');
    expect(signinTime('nonsense')).toBe('time not recorded');
  });
  it('counts the different addresses, and says nothing when none was recorded', () => {
    const s = (ip: string | null) => ({ at: null, method: 'Password', ip });
    expect(addressesNote([s('203.0.113.7'), s('203.0.113.7'), s(null)])).toBe('All from one address.');
    expect(addressesNote([s('203.0.113.7'), s('198.51.100.2')])).toBe('From 2 different addresses.');
    expect(addressesNote([s(null)])).toBeNull();
    expect(addressesNote([])).toBeNull();
  });
});

describe('SigninHistoryCard', () => {
  it('lists each sign-in with when, how and from where, and how many addresses there are', async () => {
    authFetch.mockImplementation(() =>
      json([
        { at: '2026-11-11T08:00:00+00:00', method: 'Microsoft', ip: null },
        { at: '2026-11-10T09:30:00+00:00', method: 'Password', ip: '203.0.113.7' },
        { at: '2026-11-09T09:30:00+00:00', method: 'Passkey', ip: '198.51.100.2' },
      ]),
    );
    show();
    const rows = await screen.findAllByTestId('signin-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('2026-11-11 08:00 UTC · Microsoft · address not recorded');
    expect(rows[1]).toHaveTextContent('2026-11-10 09:30 UTC · Password · 203.0.113.7');
    expect(screen.getByTestId('signin-addresses')).toHaveTextContent('From 2 different addresses.');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/auth/me/signins');
  });

  it('says none has been recorded yet for an empty list', async () => {
    authFetch.mockImplementation(() => json([]));
    show();
    expect(await screen.findByText(/No sign-in has been recorded yet/)).toBeInTheDocument();
    expect(screen.queryByTestId('signin-row')).toBeNull();
  });

  it('says so when the list cannot be read', async () => {
    authFetch.mockImplementation(() => json({}, 500));
    show();
    expect(await screen.findByTestId('signin-problem')).toHaveTextContent('could not be read');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
