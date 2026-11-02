import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const replace = vi.fn();
const begin = vi.fn();
const finish = vi.fn();
const complete = vi.fn();
const getPasskey = vi.fn();
const supported = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => new URLSearchParams('next=%2Fcases'),
  usePathname: () => '/login',
}));
vi.mock('@/lib/api', () => ({
  authApi: {
    login: vi.fn(),
    isAuthenticated: () => false,
    ssoStatus: () => Promise.resolve({ microsoft: false, password_login: 'all' }),
    completeSso: () => Promise.reject(new Error('not used here')),
    completeWithTokens: (t: unknown) => complete(t),
  },
  passkeyApi: { authenticateBegin: (e?: string) => begin(e), authenticateFinish: (c: string, cred: unknown) => finish(c, cred) },
}));
vi.mock('@/lib/webauthn', () => ({ getPasskey: (o: unknown) => getPasskey(o), isWebAuthnSupported: () => supported() }));

import LoginPage from './page';

beforeEach(() => {
  [replace, begin, finish, complete, getPasskey, supported].forEach((m) => m.mockReset());
  supported.mockReturnValue(true);
});

describe('sign in with a passkey', () => {
  it('runs the passkey check, turns the tokens into a login, and goes where the person was headed', async () => {
    begin.mockResolvedValue({ publicKey: { rp: 'x' }, challenge: 'ch1' });
    getPasskey.mockResolvedValue({ id: 'cred' });
    finish.mockResolvedValue({ access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900 });
    complete.mockResolvedValue({});
    render(<LoginPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in with a passkey' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/cases'));
    expect(begin).toHaveBeenCalledWith(undefined);
    expect(getPasskey).toHaveBeenCalledWith({ rp: 'x' });
    expect(finish).toHaveBeenCalledWith('ch1', { id: 'cred' });
    expect(complete).toHaveBeenCalledWith({ access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900 });
  });

  it('cancelling the browser prompt keeps the person on the page with a plain message', async () => {
    begin.mockResolvedValue({ publicKey: {}, challenge: 'c' });
    getPasskey.mockRejectedValue(new DOMException('no', 'NotAllowedError'));
    render(<LoginPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in with a passkey' }));
    expect(await screen.findByText(/Cancelled/)).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it('a failed passkey check shows the server message and signs nobody in', async () => {
    begin.mockResolvedValue({ publicKey: {}, challenge: 'c' });
    getPasskey.mockResolvedValue({ id: 'x' });
    finish.mockRejectedValue(new Error('Passkey not recognised'));
    render(<LoginPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in with a passkey' }));
    expect(await screen.findByText(/Passkey not recognised/)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('hides the button in a browser without passkey support', async () => {
    supported.mockReturnValue(false);
    render(<LoginPage />);
    await screen.findByRole('button', { name: /^sign in$/i });
    expect(screen.queryByRole('button', { name: 'Sign in with a passkey' })).not.toBeInTheDocument();
  });
});
