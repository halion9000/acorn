import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_TOKEN_KEY, AUTH_USER_KEY, authFetch, getImpersonation, sessionHooks } from './auth-session';
import { endImpersonation, startImpersonation } from './impersonation';

const json = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(AUTH_TOKEN_KEY, 'admin-token');
  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify({ id: 'admin', role: 'tenant_admin' }));
});
afterEach(() => vi.unstubAllGlobals());

describe('impersonation', () => {
  it('starts as the person: their token is sent from then on, and their user is saved until it ends', async () => {
    const calls: { url: string; auth: string | null }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        calls.push({ url, auth: new Headers(init?.headers).get('Authorization') });
        if (url.includes('/auth/impersonate/u1')) return json(200, { access_token: 'imp-token', label: 'analyst@example.com' });
        if (url.endsWith('/auth/me')) return json(200, { id: 'u1', role: 'soc_lead' });
        return json(200, {});
      }),
    );
    expect(await startImpersonation('u1', 'boss@example.com')).toBeNull();
    expect(calls[0]).toEqual({ url: '/api/v1/auth/impersonate/u1', auth: 'Bearer admin-token' }); // asked with the administrator's own sign-in
    expect(calls[1].auth).toBe('Bearer imp-token'); // and the next request is the person's
    expect(getImpersonation()).toEqual({ token: 'imp-token', label: 'analyst@example.com', by: 'boss@example.com' });
    expect(JSON.parse(window.localStorage.getItem(AUTH_USER_KEY) ?? '{}').role).toBe('soc_lead');

    await endImpersonation();
    expect(calls.at(-1)).toEqual({ url: '/api/v1/auth/impersonate/end/now', auth: 'Bearer imp-token' });
    expect(getImpersonation()).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(AUTH_USER_KEY) ?? '{}').role).toBe('tenant_admin'); // the administrator's own user is back
  });

  it('says the server\'s own words when it refuses, and changes nothing', async () => {
    vi.stubGlobal('fetch', vi.fn(() => json(403, { detail: 'You cannot impersonate someone with more power than you hold.' })));
    expect(await startImpersonation('u2', 'boss')).toBe('You cannot impersonate someone with more power than you hold.');
    expect(getImpersonation()).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(AUTH_USER_KEY) ?? '{}').role).toBe('tenant_admin');
  });

  it('goes back to the administrator when the one-hour token is refused', async () => {
    window.sessionStorage.setItem('aisoc.responder.impersonation', JSON.stringify({ token: 'old', label: 'x', by: 'y' }));
    const reload = vi.spyOn(sessionHooks, 'reload').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', vi.fn(() => json(401, {})));
    await authFetch('/api/v1/alerts');
    expect(getImpersonation()).toBeNull();
    expect(reload).toHaveBeenCalled();
  });
});
