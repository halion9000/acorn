/**
 * Which Settings tabs a person is offered. The server decides what anyone may do (every route checks it); the tabs only keep the screen from offering what a
 * person cannot use: Tenant access needs `manage_users`, Alert email needs `platform_admin`, from the capabilities /auth/me gave at sign-in.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const swrMutate = vi.hoisted(() => vi.fn());
vi.mock('swr', () => ({ __esModule: true, default: () => ({ data: undefined, error: undefined, isLoading: false, mutate: swrMutate }) }));

const currentUser = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({
  // The Profile tab now also shows the authenticator-app card and the password card, which read these; a mock that lacks them made their load fail with an unhandled error.
  apiErrorDetail: () => null,
  totpApi: { status: async () => ({ enabled: false, recovery_codes_left: 0 }) },
  passwordApi: { change: async () => ({ changed: true, detail: '' }) },
  __esModule: true,
  apiKeysApi: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
  deploymentApi: { getAirgapStatus: vi.fn(), getLlmStatus: vi.fn(), getLlmCredential: vi.fn(), upsertLlmCredential: vi.fn(), deleteLlmCredential: vi.fn() },
  connectorsApi: { list: vi.fn(), statuses: vi.fn() },
  authApi: { currentUser: () => currentUser(), updateUserPreferences: vi.fn() },
  tenantsApi: { details: vi.fn(), users: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: { success: vi.fn(), error: vi.fn() } }));
vi.mock('./TenantAccessPanel', async () => {
  const React = await import('react');
  return { TenantAccessPanel: (p: { canGrantAll: boolean }) => React.createElement('div', { 'data-testid': 'tenant-access-stub', 'data-grant-all': String(p.canGrantAll) }) };
});
vi.mock('./AlertEmailPanel', async () => {
  const React = await import('react');
  return { AlertEmailPanel: () => React.createElement('div', { 'data-testid': 'alert-email-stub' }) };
});

import { SettingsView } from './SettingsView';

const person = { id: 'u1', email: 'a@b.com', account_name: 'a', role: 'admin', tenant_id: 't1', capabilities: ['manage_users'] };

beforeEach(() => {
  currentUser.mockReset();
  currentUser.mockReturnValue(person);
});

describe('the Settings list when it is long', () => {
  it('brings the panel to the top of the view when an entry is chosen, so a lower entry does not leave its panel off screen', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(<SettingsView />);
    await userEvent.click(await screen.findByRole('button', { name: /^tenant access/i }));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'smooth' });
    expect(await screen.findByTestId('tenant-access-stub')).toBeInTheDocument();
  });

  it('keeps the list in a scroll area of its own beside the panel, and sets each group apart with a rule and a heading band', async () => {
    render(<SettingsView />);
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(nav.className).toMatch(/lg:sticky/);
    expect(nav.className).toMatch(/lg:overflow-y-auto/);
    expect(nav.className).toMatch(/lg:max-h-/);
    const groups = screen.getAllByTestId('settings-group');
    expect(groups.length).toBeGreaterThan(2);
    for (const g of groups) expect(g.className).toMatch(/border-t/);
  });
});
