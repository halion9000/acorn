import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const createUser = vi.hoisted(() => vi.fn());
const customRoles = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', async (original) => ({
  ...(await original<typeof import('@/lib/api')>()),
  tenantsApi: { createUser: (b: unknown) => createUser(b), customRoles: () => customRoles() },
}));

import { AddMemberForm, CUSTOM_PREFIX, memberFormProblems } from './AddMemberForm';

const made = { id: 'u9', account_name: 'jane', username: 'jane', email: null, role: 'viewer', is_active: true, last_login: null, created_at: '2026-11-02T00:00:00Z' };

beforeEach(() => {
  createUser.mockReset().mockResolvedValue(made);
  customRoles.mockReset().mockResolvedValue([{ id: 'r1', name: 'Client reviewer', description: 'Reads one client.' }]);
});

describe('adding a member with a custom role', () => {
  it('lists the custom roles of the workspace under the built-in ones', async () => {
    render(<AddMemberForm onCreated={() => undefined} onCancel={() => undefined} />);
    expect(await screen.findByRole('option', { name: 'Client reviewer' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Built-in roles' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Your custom roles' })).toBeInTheDocument();
  });

  it('choosing a custom role adds the person as a Viewer holding that role', async () => {
    render(<AddMemberForm onCreated={() => undefined} onCancel={() => undefined} />);
    await screen.findByRole('option', { name: 'Client reviewer' });
    await userEvent.type(screen.getByLabelText(/^Account name/), 'jane');
    await userEvent.type(screen.getByLabelText(/^Starting password/), 'a-long-enough-password');
    await userEvent.selectOptions(screen.getByLabelText(/^Role/), 'Client reviewer');
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(createUser).toHaveBeenCalled());
    expect(createUser.mock.calls[0][0]).toMatchObject({ role: 'viewer', custom_role_ids: ['r1'] });
  });

  it('a built-in role is sent as before, with no custom roles', async () => {
    render(<AddMemberForm onCreated={() => undefined} onCancel={() => undefined} />);
    await userEvent.type(screen.getByLabelText(/^Account name/), 'jane');
    await userEvent.type(screen.getByLabelText(/^Starting password/), 'a-long-enough-password');
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(createUser).toHaveBeenCalled());
    expect(createUser.mock.calls[0][0].role).toBe('soc_analyst');
    expect(createUser.mock.calls[0][0].custom_role_ids).toBeUndefined();
  });

  it('still works when the custom roles cannot be read', async () => {
    customRoles.mockRejectedValue(new Error('403'));
    render(<AddMemberForm onCreated={() => undefined} onCancel={() => undefined} />);
    expect(await screen.findByRole('option', { name: 'SOC analyst' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Your custom roles' })).not.toBeInTheDocument();
  });

  it('a custom role passes the form check', () => {
    expect(memberFormProblems({ accountName: 'jane', displayName: '', email: '', role: `${CUSTOM_PREFIX}r1`, password: 'a-long-enough-password' })).toEqual({});
  });
});
