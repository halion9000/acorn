import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const createUser = vi.hoisted(() => vi.fn());
const rejecting = vi.hoisted(() => ({ current: null as Error | null }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), tenantsApi: { createUser: (b: unknown) => rejecting.current ? Promise.reject(rejecting.current) : createUser(b) } }));

import { ApiError } from '@/lib/api';
import { AddMemberForm, MEMBER_ROLES, MIN_PASSWORD_LENGTH, generatePassword, memberFormProblems } from './AddMemberForm';

const byLabel = (name: string) => screen.getByLabelText(new RegExp(`^${name}`));
const good = { accountName: 'jane.doe', displayName: 'Jane Doe', email: 'jane@example.com', role: 'soc_analyst', password: 'a-long-enough-password' };
const created = { id: 'u9', account_name: 'jane.doe', username: 'Jane Doe', email: 'jane@example.com', role: 'soc_analyst', is_active: true, last_login: null, created_at: '2026-11-01T00:00:00Z' };

beforeEach(() => {
  createUser.mockReset();
  rejecting.current = null;
});

describe('memberFormProblems', () => {
  it('has nothing to say about a good form, and email and display name are optional', () => {
    expect(memberFormProblems(good)).toEqual({});
    expect(memberFormProblems({ ...good, email: '', displayName: '' })).toEqual({});
  });

  it('says what is wrong with the account name, email, role and password', () => {
    for (const bad of ['', 'ab', 'Has Space', '-leading', 'trailing-', 'x'.repeat(33), 'bad!char']) expect(memberFormProblems({ ...good, accountName: bad }).accountName, bad).toBeTruthy();
    for (const ok of ['abc', 'a.b-c_d', 'JANE.DOE', 'x'.repeat(32)]) expect(memberFormProblems({ ...good, accountName: ok }).accountName, ok).toBeUndefined();
    expect(memberFormProblems({ ...good, email: 'not-an-email' }).email).toBeTruthy();
    expect(memberFormProblems({ ...good, role: 'god' }).role).toBeTruthy();
    expect(memberFormProblems({ ...good, password: 'short' }).password).toContain(String(MIN_PASSWORD_LENGTH));
    expect(memberFormProblems({ ...good, password: 'x'.repeat(MIN_PASSWORD_LENGTH - 1) }).password).toBeTruthy();
    expect(memberFormProblems({ ...good, password: 'x'.repeat(MIN_PASSWORD_LENGTH) }).password).toBeUndefined();
  });

  it('offers only roles an administrator can reasonably hand out, never a platform or service role', () => {
    expect(MEMBER_ROLES.map((r) => r.value)).toEqual(['viewer', 'soc_analyst', 'threat_hunter', 'soc_lead', 'tenant_admin']);
  });
});

describe('generatePassword', () => {
  it('is the length asked for, from letters and digits without look-alikes', () => {
    const p = generatePassword();
    expect(p).toHaveLength(20);
    expect(p).toMatch(/^[A-HJ-NP-Za-km-z2-9]+$/);
    expect(generatePassword(32)).toHaveLength(32);
  });

  it('is different each time, and meets the form\'s own minimum', () => {
    const seen = new Set(Array.from({ length: 50 }, () => generatePassword()));
    expect(seen.size).toBe(50);
    expect(memberFormProblems({ ...good, password: generatePassword() }).password).toBeUndefined();
  });

  it('skips random values that would favour the first letters, and keeps asking until it has enough', () => {
    const calls: number[] = [];
    const random = (n: number) => {
      calls.push(n);
      // first batch: all values at or above the unbiased limit (refused); then ordinary values
      return calls.length === 1 ? new Uint32Array(n).fill(0xffffffff) : new Uint32Array(n).map((_, i) => i);
    };
    const p = generatePassword(10, random);
    expect(p).toHaveLength(10);
    expect(calls.length).toBeGreaterThan(1);
  });
});

describe('AddMemberForm', () => {
  const fill = async (over: Partial<typeof good> = {}) => {
    const v = { ...good, ...over };
    await userEvent.type(byLabel('Account name'), v.accountName);
    if (v.displayName) await userEvent.type(byLabel('Display name'), v.displayName);
    if (v.email) await userEvent.type(byLabel('Email'), v.email);
    await userEvent.selectOptions(byLabel('Role'), v.role);
    await userEvent.type(byLabel('Starting password'), v.password);
  };

  it('sends what was typed (account name lower-cased and trimmed), and shows the password once it succeeds', async () => {
    createUser.mockResolvedValue(created);
    const onCreated = vi.fn();
    render(<AddMemberForm onCreated={onCreated} onCancel={vi.fn()} />);
    await fill({ accountName: ' Jane.Doe ', role: 'viewer' });
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(createUser).toHaveBeenCalledTimes(1));
    expect(createUser).toHaveBeenCalledWith({ account_name: 'jane.doe', username: 'Jane Doe', email: 'jane@example.com', password: good.password, role: 'viewer' });
    expect(onCreated).toHaveBeenCalledWith(created);
    expect(await screen.findByTestId('member-added')).toHaveTextContent('jane.doe');
    expect(screen.getByTestId('member-password')).toHaveTextContent(good.password);
    expect(screen.getByText(/no page yet where a person changes their own password/i)).toBeInTheDocument();
  });

  it('leaves out an empty display name and email instead of sending blanks', async () => {
    createUser.mockResolvedValue(created);
    render(<AddMemberForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    await fill({ displayName: '', email: '' });
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(createUser).toHaveBeenCalled());
    expect(createUser.mock.calls[0][0]).toEqual({ account_name: 'jane.doe', username: undefined, email: undefined, password: good.password, role: 'soc_analyst' });
  });

  it('sends nothing and says what is wrong when the form is not right', async () => {
    render(<AddMemberForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    expect(createUser).not.toHaveBeenCalled();
    expect(await screen.findByText('Choose the name this person signs in with.')).toBeInTheDocument();
    expect(screen.getByText(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)).toBeInTheDocument();
  });

  it('Generate fills in a strong password and shows it', async () => {
    render(<AddMemberForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    const box = byLabel('Starting password') as HTMLInputElement;
    expect(box.value).toHaveLength(20);
    expect(box.type).toBe('text');
    await userEvent.click(screen.getByRole('button', { name: 'Hide' }));
    expect(box.type).toBe('password');
  });

  it('shows the server\'s reason when it refuses (a taken name, or a role that is too high) and keeps the form so nothing is retyped', async () => {
    rejecting.current = new ApiError('API 409 - /x', 409, JSON.stringify({ detail: 'That account name is already taken. Choose another.' }));
    render(<AddMemberForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    await fill();
    await userEvent.click(screen.getByRole('button', { name: 'Add member' }));
    expect(await screen.findByTestId('member-error')).toHaveTextContent('already taken');
    expect(screen.queryByTestId('member-added')).toBeNull();
    expect((byLabel('Account name') as HTMLInputElement).value).toBe('jane.doe');
    expect(screen.getByRole('button', { name: 'Add member' })).toBeEnabled();
  });

  it('Cancel closes it without sending anything', async () => {
    const onCancel = vi.fn();
    render(<AddMemberForm onCreated={vi.fn()} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
    expect(createUser).not.toHaveBeenCalled();
  });
});
