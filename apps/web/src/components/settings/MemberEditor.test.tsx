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

const plain: TenantUser = { ...ann, custom_roles: [] };
const reviewer: TenantUser = { ...ann, role: 'custom', custom_roles: [{ id: 'r1', name: 'Client reviewer' }] };

describe('editing a member: one Role dropdown holds the built-in and the custom roles', () => {
  it('lists built-in roles and custom roles in the same dropdown, and no separate custom roles area', () => {
    open(plain);
    expect(screen.getByRole('group', { name: 'Built-in roles' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Your custom roles' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Billing' })).toBeInTheDocument();
    expect(screen.queryByText('Custom roles')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('a person whose one role is a custom role is shown as that custom role', () => {
    open(reviewer);
    expect(screen.getByLabelText(/^Role/)).toHaveValue('custom:r1');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('choosing a custom role for someone with a built-in role makes it their one role', async () => {
    open(plain);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'Billing');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', role: 'custom', custom_role_ids: ['r2'] }));
    expect(changed).toEqual([false]);
  });

  it('moving from one custom role to another sends the new one as their only role', async () => {
    open(reviewer);
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'Billing');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', role: 'custom', custom_role_ids: ['r2'] }));
  });

  it('choosing a built-in role sets it and clears any custom roles', async () => {
    open(reviewer);
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'SOC lead');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', role: 'soc_lead', custom_role_ids: [] }));
  });

  it('a built-in role for someone with no custom roles sends just the role', async () => {
    open(plain);
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'SOC lead');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann', role: 'soc_lead' }));
  });

  it('a mix that is not one single choice is kept as it is until a role is picked', async () => {
    open(ann); // SOC analyst plus a custom role
    const select = screen.getByLabelText(/^Role/);
    expect(select).toHaveValue('__keep');
    expect(screen.getByRole('option', { name: /Keep as it is \(SOC analyst \+ Client reviewer\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Display name/), '!');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith('u1', { username: 'Ann!' })); // the name changed; the roles did not
  });

  it('shows the refusal of the server as it is and does not reload the list', async () => {
    updateUser.mockRejectedValue(refusal('This is the only active administrator. Changing this role would lock everyone out.'));
    open({ ...plain, role: 'tenant_admin' });
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
    await userEvent.click(screen.getByRole('button', { name: 'Reset second factor' }));
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
