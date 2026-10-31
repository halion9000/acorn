import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const demo = vi.hoisted(() => ({ on: false }));
vi.mock('@/lib/demoMode', () => ({ isDemoMode: () => demo.on }));
vi.mock('./Sidebar', () => ({ Sidebar: () => <nav data-testid="sidebar" /> }));
vi.mock('./TopBar', () => ({ TopBar: () => <header data-testid="topbar" /> }));
vi.mock('./HiddenPageGuard', () => ({ HiddenPageGuard: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('./CommandPalette', () => ({ CommandPalette: () => null }));
vi.mock('./TimeWindowProvider', () => ({ TimeWindowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('./TenantProvider', () => ({ TenantProvider: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('./TenantViewBanner', () => ({ TenantViewBanner: () => null }));
vi.mock('@/components/copilot/CopilotDock', () => ({ CopilotDock: () => null }));
vi.mock('@/components/demo/DemoBanner', () => ({ DemoBanner: () => null }));
vi.mock('@/components/demo/DemoAutoLogin', () => ({ DemoAutoLogin: () => null }));
vi.mock('@/components/util/ClientOnly', () => ({ ClientOnly: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import { AUTH_REFRESH_KEY, AUTH_TOKEN_KEY, sessionHooks } from '@/lib/auth-session';
import { AppShell } from './AppShell';

let redirect: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  demo.on = false;
  window.localStorage.clear();
  window.history.replaceState({}, '', '/alerts?x=1');
  redirect = vi.spyOn(sessionHooks, 'redirectToLogin').mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const page = () => render(<AppShell><p data-testid="page">the page</p></AppShell>);

describe('AppShell sign-in gate', () => {
  it('in a production build with no saved sign-in it draws nothing of the console and goes to the login page', () => {
    vi.stubEnv('NODE_ENV', 'production');
    page();
    expect(screen.queryByTestId('page')).toBeNull();
    expect(screen.queryByTestId('sidebar')).toBeNull();
    expect(redirect).toHaveBeenCalledWith('/alerts?x=1');
  });

  it('in a production build with a saved sign-in it draws the console', () => {
    vi.stubEnv('NODE_ENV', 'production');
    window.localStorage.setItem(AUTH_TOKEN_KEY, 'tok');
    page();
    expect(screen.getByTestId('page')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('a refresh token alone also counts: the session machinery renews the access token', () => {
    vi.stubEnv('NODE_ENV', 'production');
    window.localStorage.setItem(AUTH_REFRESH_KEY, 'r1');
    page();
    expect(screen.getByTestId('page')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('demo mode and development builds are not gated', () => {
    vi.stubEnv('NODE_ENV', 'production');
    demo.on = true;
    page();
    expect(screen.getByTestId('page')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('a development build draws at once without a sign-in', () => {
    vi.stubEnv('NODE_ENV', 'development');
    page();
    expect(screen.getByTestId('page')).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });
});
