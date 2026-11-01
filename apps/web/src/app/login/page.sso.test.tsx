/**
 * Sign in with Microsoft on the sign-in page: the button shows only when the server has it set up, a one-time code in the address is traded for a session, and a refusal from the server is explained in plain words.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const replace = vi.fn();
const ssoStatus = vi.fn();
const completeSso = vi.fn();
const isAuthenticated = vi.fn();
let query = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => new URLSearchParams(query),
  usePathname: () => '/login',
}));

vi.mock('@/lib/api', () => ({
  authApi: {
    login: vi.fn(),
    isAuthenticated: () => isAuthenticated(),
    ssoStatus: () => ssoStatus(),
    completeSso: (code: string) => completeSso(code),
  },
}));

import LoginPage from './page';

beforeEach(() => {
  [replace, ssoStatus, completeSso, isAuthenticated].forEach((m) => m.mockReset());
  isAuthenticated.mockReturnValue(false);
  ssoStatus.mockResolvedValue({ microsoft: false, password_login: 'all' });
  query = '';
});

describe('Sign in with Microsoft button', () => {
  it('is not shown when the server has not set it up', async () => {
    render(<LoginPage />);
    await waitFor(() => expect(ssoStatus).toHaveBeenCalled());
    expect(screen.queryByRole('link', { name: /sign in with microsoft/i })).toBeNull();
  });

  it('is shown when it is set up, and starts the server-side flow carrying where the person was headed', async () => {
    ssoStatus.mockResolvedValue({ microsoft: true, password_login: 'all' });
    query = 'next=%2Falerts';
    render(<LoginPage />);
    const link = await screen.findByRole('link', { name: /sign in with microsoft/i });
    expect(link).toHaveAttribute('href', '/api/v1/auth/sso/microsoft/login?next=%2Falerts');
  });

  it('never carries a "next" that leaves the site', async () => {
    ssoStatus.mockResolvedValue({ microsoft: true, password_login: 'all' });
    query = 'next=https%3A%2F%2Fevil.example';
    render(<LoginPage />);
    const link = await screen.findByRole('link', { name: /sign in with microsoft/i });
    expect(link).toHaveAttribute('href', '/api/v1/auth/sso/microsoft/login?next=%2Fdashboard');
  });

  it('says passwords are for administrators when the server limits them', async () => {
    ssoStatus.mockResolvedValue({ microsoft: true, password_login: 'admins' });
    render(<LoginPage />);
    expect(await screen.findByText(/administrators can also sign in with an account name and password/i)).toBeInTheDocument();
  });
});

describe('coming back from Microsoft', () => {
  it('trades the one-time code for a session and goes on to the page the person wanted', async () => {
    completeSso.mockResolvedValue({});
    query = 'sso=abc123&next=%2Fcases';
    render(<LoginPage />);
    await waitFor(() => expect(completeSso).toHaveBeenCalledWith('abc123'));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/cases'));
  });

  it('does not run the "already signed in" shortcut before the code has been traded', async () => {
    isAuthenticated.mockReturnValue(true); // an older session is still in the browser
    completeSso.mockResolvedValue({});
    query = 'sso=abc123';
    render(<LoginPage />);
    await waitFor(() => expect(completeSso).toHaveBeenCalledTimes(1));
  });

  it('tells the person when the code was used or expired, and shows the form again', async () => {
    completeSso.mockRejectedValue(new Error('401'));
    query = 'sso=stale';
    render(<LoginPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('expired or was already used');
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/account name/i)).toBeInTheDocument();
  });

  it.each([
    ['group', 'not in the group'],
    ['no_account', 'no account here'],
    ['disabled', 'turned off'],
    ['tenant', 'different organization'],
    ['state', 'took too long'],
  ])('explains "%s" in plain words', async (code, words) => {
    query = `sso_error=${code}`;
    render(<LoginPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent(new RegExp(words, 'i'));
    expect(completeSso).not.toHaveBeenCalled();
  });

  it('gives a general sentence for a code it does not know, never the raw code', async () => {
    query = 'sso_error=zzz_weird';
    render(<LoginPage />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/did not work/i);
    expect(alert.textContent).not.toContain('zzz_weird');
  });
});
