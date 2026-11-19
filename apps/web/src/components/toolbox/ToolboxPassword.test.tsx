import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { ToolboxView, confirmLines, generatePassword, startingValues } from './ToolboxView';

const f = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({ key, label, kind, options: [], required: true, hint: '', ...extra });
const PASSWORD_TOOL = {
  id: 'change_password',
  group: 'Password and security',
  label: 'Change a password',
  risk: 'medium',
  reversible: false,
  summary: 'Set a new password.',
  fields: [
    f('ticket', 'Ticket number', 'ticket', { required: false }),
    f('user', 'Person', 'user'),
    f('entra_override', 'User Entra override', 'email', { required: false }),
    f('require_change', 'Require a password change at next sign-in', 'choice', { options: ['Yes', 'No'], default: 'Yes' }),
    f('password', 'Password', 'secret'),
  ],
};
const lookups = { people: [{ email: 'ann@acme.com', name: 'Ann Lee', enabled: true, guest: false }], domains: ['acme.com'] };

beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
  listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme' }]);
  authFetch.mockImplementation(async (url: string) => {
    if (url.endsWith('/tools')) return { ok: true, json: async () => ({ groups: ['Password and security'], stage: 's', tools: [PASSWORD_TOOL] }) };
    if (url.includes('/lookups')) return { ok: true, json: async () => lookups };
    return { ok: true, json: async () => ({ title: 'Change a password: ann@acme.com' }) };
  });
});
afterEach(() => cleanup());

describe('generatePassword', () => {
  it('makes 16 characters with a capital, a small letter, a digit and a symbol, never the look-alike letters', () => {
    for (let i = 0; i < 40; i++) {
      const pw = generatePassword((n) => Math.floor(Math.random() * n));
      expect(pw).toHaveLength(16);
      expect(pw).toMatch(/[A-Z]/);
      expect(pw).toMatch(/[a-z]/);
      expect(pw).toMatch(/[0-9]/);
      expect(pw).toMatch(/[!@#$%&*?]/);
      expect(pw).not.toMatch(/[Il1O0]/);
    }
  });

  it('uses the secure browser random by default and gives a different password each time', () => {
    const seen = new Set(Array.from({ length: 20 }, () => generatePassword()));
    expect(seen.size).toBe(20);
  });
});

describe('starting values and the confirmation', () => {
  it('starts Require a password change on Yes and fills in a generated password', () => {
    const v = startingValues(PASSWORD_TOOL as never, () => 0);
    expect(v.require_change).toBe('Yes');
    expect(v.password).toHaveLength(16);
    expect(v.user).toBeUndefined();
  });

  it('hides a password in the confirmation and says when no ticket was given', () => {
    const lines = confirmLines(PASSWORD_TOOL as never, { user: 'ann@acme.com', password: 'Secret-Value-1', require_change: 'Yes' });
    expect(lines.find((l) => l.label === 'Password')!.value).toBe('(hidden)');
    expect(JSON.stringify(lines)).not.toContain('Secret-Value-1');
    expect(lines.at(-1)).toEqual({ label: 'Ticket number', value: 'none given: a new ticket is opened when this runs' });
    expect(confirmLines(PASSWORD_TOOL as never, { user: 'a@b.co', ticket: '4711' }).some((l) => l.label === 'Ticket number' && l.value === '4711')).toBe(true);
  });
});

describe('the Change a password form', () => {
  it('asks for the ticket, person, Entra override, the change at next sign-in and a password, with the password generated', async () => {
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Change a password/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    expect((screen.getByLabelText('Require a password change at next sign-in') as HTMLSelectElement).value).toBe('Yes');
    const pw = screen.getByLabelText('Password') as HTMLInputElement;
    expect(pw.type).toBe('password');
    expect(pw.value).toHaveLength(16);
    expect(screen.getByLabelText('Ticket number')).toBeInTheDocument();
    expect(screen.getByLabelText('User Entra override')).toBeInTheDocument();
    const first = pw.value;
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect((screen.getByLabelText('Password') as HTMLInputElement).value).not.toBe(first);
    await userEvent.click(screen.getByRole('button', { name: 'Show' }));
    expect((screen.getByLabelText('Password') as HTMLInputElement).type).toBe('text');
  });

  it('takes only digits in the ticket, sends the typed password and the choices, and never shows the password in the box', async () => {
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Change a password/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Ticket number'), 'T47x11');
    expect((screen.getByLabelText('Ticket number') as HTMLInputElement).value).toBe('4711');
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.selectOptions(screen.getByLabelText('Require a password change at next sign-in'), 'No');
    await userEvent.clear(screen.getByLabelText('Password'));
    await userEvent.type(screen.getByLabelText('Password'), 'My-Own-Pass-77');
    await userEvent.click(screen.getByRole('button', { name: 'Save request' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('(hidden)');
    expect(dialog.textContent).not.toContain('My-Own-Pass-77');
    expect(dialog.textContent).toContain('4711');
    await userEvent.click(screen.getByRole('button', { name: 'Yes, save it' }));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/request'))).toBe(true));
    const sent = JSON.parse((authFetch.mock.calls.find((c) => String(c[0]).endsWith('/request'))![1] as RequestInit).body as string);
    expect(sent.args).toMatchObject({ ticket: '4711', user: 'ann@acme.com', require_change: 'No', password: 'My-Own-Pass-77' });
    expect(sent.args.entra_override).toBeUndefined();
  });
});
