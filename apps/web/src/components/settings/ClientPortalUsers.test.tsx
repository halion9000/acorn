import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const users = vi.hoisted(() => vi.fn());
const create = vi.hoisted(() => vi.fn());
const resetMfa = vi.hoisted(() => vi.fn());
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    clientPortalApi: { users: () => users(), create: (b: unknown) => create(b), resetMfa: (id: string) => resetMfa(id), turnOff: vi.fn() },
    msspApi: { listChildren: () => Promise.resolve([{ id: 'c1', name: 'Acme Dental', mssp_role: 'child' }]) },
  };
});

import { ClientPortalUsers } from './ClientPortalUsers';

const row = (over: Record<string, unknown> = {}) => ({
  id: 'u1',
  tenant_id: 'c1',
  client_name: 'Acme Dental',
  account_name: 'acme.owner',
  username: 'acme.owner',
  email: null,
  is_active: true,
  last_login: null,
  mfa_enabled: false,
  ...over,
});

beforeEach(() => {
  users.mockReset();
  create.mockReset();
  resetMfa.mockReset();
});
afterEach(() => cleanup());

describe('Client dashboard sign-ins (Settings)', () => {
  it('draws nothing for someone the server refuses', async () => {
    users.mockRejectedValue(new Error('403'));
    const { container } = render(<ClientPortalUsers />);
    await waitFor(() => expect(users).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('lists each sign-in with its client and whether the authenticator app is set up', async () => {
    users.mockResolvedValue([row(), row({ id: 'u2', account_name: 'acme.two', mfa_enabled: true })]);
    render(<ClientPortalUsers />);
    expect(await screen.findByText('acme.owner')).toBeTruthy();
    expect(screen.getByText(/no authenticator app yet/)).toBeTruthy();
    expect(screen.getByText(/authenticator app set up/)).toBeTruthy();
  });

  it('creates a sign-in for the chosen client and shows the temporary password once', async () => {
    users.mockResolvedValue([]);
    create.mockResolvedValue({ ...row(), temporary_password: 'Tmp-Pass-123' });
    render(<ClientPortalUsers />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add a client sign-in' }));
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Account name'), 'acme.owner');
    await userEvent.click(screen.getByRole('button', { name: 'Create sign-in' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ child_tenant_id: 'c1', account_name: 'acme.owner' }));
    expect((await screen.findByTestId('portal-temp-password')).textContent).toContain('Tmp-Pass-123');
  });

  it('resets the second step of one person', async () => {
    users.mockResolvedValue([row()]);
    resetMfa.mockResolvedValue({ done: true, detail: 'ok' });
    render(<ClientPortalUsers />);
    await userEvent.click(await screen.findByRole('button', { name: 'Reset second step' }));
    await waitFor(() => expect(resetMfa).toHaveBeenCalledWith('u1'));
  });
});
