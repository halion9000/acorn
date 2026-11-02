import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const updateUser = vi.hoisted(() => vi.fn());
const deleteUser = vi.hoisted(() => vi.fn());
const resetUserPassword = vi.hoisted(() => vi.fn());
const signUserOut = vi.hoisted(() => vi.fn());
const resetUserMfa = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  tenantsApi: {
    updateUser: (id: string, b: unknown) => updateUser(id, b),
    deleteUser: (id: string) => deleteUser(id),
    resetUserPassword: (id: string, p: string) => resetUserPassword(id, p),
    signUserOut: (id: string) => signUserOut(id),
    resetUserMfa: (id: string) => resetUserMfa(id),
  },
}));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import { ApiError, type TenantUser } from '@/lib/api';
import { MemberEditor } from './MemberEditor';

const ann: TenantUser = { id: 'u1', account_name: 'ann', username: 'Ann', email: 'ann@example.com', role: 'soc_analyst', is_active: true, last_login: null, created_at: '2026-11-02T00:00:00Z', custom_roles: [{ id: 'r1', name: 'Client reviewer' }] };
const roles = [
  { id: 'r1', name: 'Client reviewer', description: null },
  { id: 'r2', name: 'Billing', description: null },
];
let changed: Array<boolean | undefined>;
const refusal = (detail: string) => new ApiError('409', 409, JSON.stringify({ detail }));

function open(member: TenantUser = ann, isSelf = false) {
  changed = [];
  return render(<MemberEditor member={member} isSelf={isSelf} customRoles={roles} onChanged={(g) => changed.push(g)} onClose={() => undefined} />);
}

beforeEach(() => {
  [updateUser, deleteUser, resetUserPassword, signUserOut, resetUserMfa].forEach((m) => m.mockReset().mockResolvedValue({ done: true, detail: 'ok' }));
});

describe('editing a member', () => {
  it('saves only what changed: a new role set, not the built-in role', async () => {
    open();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText('Billing'));
    await userEvent.click(screen.getByLabelText('Client reviewer'));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', custom_role_ids: ['r2'] }));
    expect(changed).toEqual([false]);
  });

  it('changing the built-in role sends the role', async () => {
    open();
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'SOC lead');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', role: 'soc_lead' }));
  });

  it('shows the refusal of the server as it is and does not reload the list', async () => {
    updateUser.mockRejectedValue(refusal('This is the only active administrator. Changing this role would lock everyone out.'));
    open({ ...ann, role: 'tenant_admin' });
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'Viewer');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByTestId('member-edit-error')).toHaveTextContent(/only active administrator/);
    expect(changed).toEqual([]);
  });

  it('you cannot change your own role, disable or delete yourself here', () => {
    open(ann, true);
    expect(screen.getByLabelText(/^Role/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Delete…' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Disable account' })).not.toBeInTheDocument();
  });
});

describe('account actions', () => {
  it('delete asks first, names the person, and only then deletes and tells the list the person is gone', async () => {
    open();
    await userEvent.click(screen.getByRole('button', { name: 'Delete…' }));
    expect(deleteUser).not.toHaveBeenCalled();
    expect(screen.getByText(/Ann is removed from the workspace/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith('u1'));
    expect(changed).toEqual([true]);
  });

  it('a refused delete shows why and keeps the person', async () => {
    deleteUser.mockRejectedValue(refusal('This person cannot be deleted because cases still refer to them. Disable the account instead.'));
    open();
    await userEvent.click(screen.getByRole('button', { name: 'Delete…' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByTestId('member-edit-error')).toHaveTextContent(/Disable the account instead/);
    expect(changed).toEqual([]);
  });

  it('reset MFA and sign-out each ask before acting', async () => {
    open();
    await userEvent.click(screen.getByRole('button', { name: /Reset MFA/ }));
    expect(resetUserMfa).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove passkeys' }));
    await waitFor(() => expect(resetUserMfa).toHaveBeenCalledWith('u1'));
    await userEvent.click(screen.getByRole('button', { name: 'Sign out everywhere' }));
    expect(signUserOut).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(signUserOut).toHaveBeenCalledWith('u1'));
  });

  it('disabling asks first', async () => {
    open();
    await userEvent.click(screen.getByRole('button', { name: 'Disable account' }));
    expect(updateUser).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { is_active: false }));
  });

  it('a short password is refused before any request; a good one is reset and shown once', async () => {
    open();
    await userEvent.type(screen.getByLabelText('New password'), 'short');
    await userEvent.click(screen.getByRole('button', { name: 'Reset password' }));
    expect(resetUserPassword).not.toHaveBeenCalled();
    expect(screen.getByTestId('member-edit-error')).toHaveTextContent(/at least 12/);
    await userEvent.clear(screen.getByLabelText('New password'));
    await userEvent.type(screen.getByLabelText('New password'), 'a-long-enough-new-password');
    await userEvent.click(screen.getByRole('button', { name: 'Reset password' }));
    await waitFor(() => expect(resetUserPassword).toHaveBeenCalledWith('u1', 'a-long-enough-new-password'));
    expect(await screen.findByTestId('member-new-password')).toHaveTextContent('a-long-enough-new-password');
  });
});
