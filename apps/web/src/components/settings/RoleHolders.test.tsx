import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { RoleHolders, holdersHeading, sinceLabel } from './RoleHolders';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><RoleHolders roleId="r1" /></SWRConfig>);

beforeEach(() => {
  authFetch.mockReset();
});

describe('sinceLabel and holdersHeading', () => {
  it('gives the day, or nothing for no date or a bad one', () => {
    expect(sinceLabel('2026-11-10T09:30:00+00:00')).toBe('since 2026-11-10');
    expect(sinceLabel(null)).toBe('');
    expect(sinceLabel('nonsense')).toBe('');
  });
  it('counts people, in the singular for one, and says when nobody holds the role', () => {
    expect(holdersHeading(3)).toBe('Held by 3 people');
    expect(holdersHeading(1)).toBe('Held by 1 person');
    expect(holdersHeading(0)).toBe('Nobody holds this role');
  });
});

describe('RoleHolders', () => {
  it('lists each holder with the day they got the role, the address when it differs from the name, and a mark on an account turned off', async () => {
    authFetch.mockImplementation(() =>
      json([
        { user_id: 'u1', name: 'Bea', email: 'bea@x.test', since: '2026-08-01T00:00:00+00:00', active: false },
        { user_id: 'u2', name: 'amy@x.test', email: 'amy@x.test', since: null, active: true },
      ]),
    );
    show();
    expect(await screen.findByTestId('role-holders')).toHaveTextContent('Held by 2 people');
    const rows = screen.getAllByTestId('role-holder');
    expect(rows[0]).toHaveTextContent('Bea (bea@x.test) since 2026-08-01 · account turned off');
    expect(rows[1].textContent?.trim()).toBe('amy@x.test');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/rbac/roles/r1/holders');
  });

  it('says nobody holds the role when the list is empty', async () => {
    authFetch.mockImplementation(() => json([]));
    show();
    expect(await screen.findByTestId('role-holders')).toHaveTextContent('Nobody holds this role');
    expect(screen.queryByTestId('role-holder')).toBeNull();
  });

  it('shows nothing when the list cannot be read', async () => {
    authFetch.mockImplementation(() => json({}, 500));
    show();
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('role-holders')).toBeNull();
  });
});
