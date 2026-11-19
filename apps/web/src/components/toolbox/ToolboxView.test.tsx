import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { ToolboxView, addToList, confirmLines, isComplete, personLabel, removeFromList } from './ToolboxView';

const catalog = {
  groups: ['Password and security'],
  stage: 's',
  tools: [
    {
      id: 'reset_mfa',
      group: 'Password and security',
      label: "Reset a person's MFA",
      risk: 'high',
      reversible: false,
      summary: 'Remove their methods.',
      fields: [
        { key: 'user', label: 'Person', kind: 'user', options: [], required: true, hint: '' },
        { key: 'reason', label: 'Why', kind: 'text', options: [], required: true, hint: '' },
      ],
    },
    {
      id: 'offboard_user',
      group: 'Password and security',
      label: 'Offboard a person',
      risk: 'high',
      reversible: false,
      summary: 'Wind up an account.',
      fields: [
        { key: 'user', label: 'Person', kind: 'user', options: [], required: true, hint: '' },
        { key: 'mailbox', label: 'Mailbox', kind: 'choice', options: ['Convert to a shared mailbox', 'Keep as it is'], required: true, hint: '' },
        { key: 'when', label: 'Do it at', kind: 'datetime', options: [], required: true, hint: '' },
        { key: 'mailbox_access', label: 'Who gets access to the mailbox', kind: 'users', options: [], required: false, hint: '' },
      ],
    },
  ],
};
const lookups = { people: [{ email: 'ann@acme.com', name: 'Ann Lee', enabled: true, guest: false }, { email: 'old@acme.com', name: 'Old Hand', enabled: false, guest: false }], domains: ['acme.com'] };

beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
  listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme' }]);
});
afterEach(() => cleanup());

describe('ToolboxView', () => {
  it('lists the tools with their risk, needs a client and every field, and sends the request', async () => {
    authFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
      if (url.includes('/lookups')) return { ok: true, json: async () => lookups };
      return { ok: true, json: async () => ({ title: "Reset a person's MFA: ann@acme.com", note: 'Queued for CORE.' }), init };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    expect(screen.getAllByText('high risk, not easily reversed').length).toBe(2);
    const ask = screen.getByRole('button', { name: 'Run request' }) as HTMLButtonElement;
    expect(ask.disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    expect(ask.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'lost phone');
    expect(ask.disabled).toBe(false);
    await userEvent.click(ask);
    const dialog = await screen.findByRole('dialog', { name: 'Are you sure?' });
    expect(dialog.textContent).toContain('Acme');
    expect(dialog.textContent).toContain('ann@acme.com');
    expect(dialog.textContent).toContain('lost phone');
    expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/request'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Yes, run it' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/toolbox/request', expect.objectContaining({ method: 'POST' })));
    const sent = JSON.parse((authFetch.mock.calls.find((c) => String(c[0]).endsWith('/request'))![1] as RequestInit).body as string);
    expect(sent).toEqual({ tool: 'reset_mfa', client_id: 'c1', args: { user: 'ann@acme.com', reason: 'lost phone' } });
    expect((await screen.findByRole('status')).textContent).toContain('Queued');
  });

  it('shows the server reason when a request is refused, and a plain message when the toolbox is not allowed', async () => {
    authFetch.mockImplementation(async (url: string) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
      return { ok: false, status: 422, json: async () => ({ detail: 'Why is needed.' }) };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Run request' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, run it' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Why is needed.');
    cleanup();
    authFetch.mockReset();
    authFetch.mockResolvedValue({ ok: false, status: 403 });
    render(<ToolboxView />);
    expect((await screen.findByRole('alert')).textContent).toContain('needs the alerts permission');
  });
});

describe('pickers', () => {
  it('offers the chosen clients own people, a fixed list for choices, and sends the picked values', async () => {
    authFetch.mockImplementation(async (url: string) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
      if (url.includes('/lookups')) return { ok: true, json: async () => lookups };
      return { ok: true, json: async () => ({ title: 'Offboard a person: ann@acme.com' }) };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Offboard a person/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/toolbox/lookups?client_id=c1'));
    await waitFor(() => expect(document.querySelectorAll('#people-user option').length).toBe(2));
    expect(document.querySelector('#people-user option[value="old@acme.com"]')!.getAttribute('label')).toBe('Old Hand (old@acme.com) - sign-in off');
    const mailbox = screen.getByLabelText('Mailbox') as HTMLSelectElement;
    expect(Array.from(mailbox.options).map((o) => o.value)).toEqual(['', 'Convert to a shared mailbox', 'Keep as it is']);
    expect(screen.getByText('Who gets access to the mailbox (optional)')).toBeTruthy();
    const ask = screen.getByRole('button', { name: 'Run request' }) as HTMLButtonElement;
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.selectOptions(mailbox, 'Keep as it is');
    expect(ask.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Do it at'), { target: { value: '2026-12-05T17:00' } });
    expect(ask.disabled).toBe(false);
    await userEvent.type(screen.getByLabelText('Who gets access to the mailbox'), 'old@acme.com');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    await userEvent.click(ask);
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, run it' }));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/request'))).toBe(true));
    const sent = JSON.parse((authFetch.mock.calls.find((c) => String(c[0]).endsWith('/request'))![1] as RequestInit).body as string);
    expect(sent.args).toEqual({ user: 'ann@acme.com', mailbox: 'Keep as it is', when: '2026-12-05T17:00', mailbox_access: 'old@acme.com' });
  });
});

describe('helpers', () => {
  it('shows a person with their address, notes a switched-off or guest account, and keeps a comma list free of repeats', () => {
    expect(personLabel({ email: 'a@b.co', name: 'Ann', enabled: true, guest: false })).toBe('Ann (a@b.co)');
    expect(personLabel({ email: 'a@b.co', name: 'a@b.co', enabled: false, guest: true })).toBe('a@b.co - sign-in off - guest');
    expect(addToList('a@b.co', 'c@d.co')).toBe('a@b.co, c@d.co');
    expect(addToList('a@b.co', 'a@b.co')).toBe('a@b.co');
    expect(removeFromList('a@b.co, c@d.co', 'a@b.co')).toBe('c@d.co');
  });

  it('is ready only with a client and every required field', () => {
    const tool = { id: 't', group: 'g', label: 'l', risk: 'low' as const, reversible: true, summary: '', fields: [{ key: 'a', label: 'A', kind: 'text' as const, options: [], required: true, hint: '' }, { key: 'b', label: 'B', kind: 'text' as const, options: [], required: false, hint: '' }] };
    expect(isComplete(tool, 'c1', { a: 'x' })).toBe(true);
    expect(isComplete(tool, '', { a: 'x' })).toBe(false);
    expect(isComplete(tool, 'c1', { b: 'x' })).toBe(false);
  });
});

describe('the confirmation', () => {
  it('sends nothing when the person cancels, and lists only the values that were filled in', async () => {
    authFetch.mockImplementation(async (url: string) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
      if (url.includes('/lookups')) return { ok: true, json: async () => lookups };
      return { ok: true, json: async () => ({ title: 'x' }) };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'lost phone');
    await userEvent.click(screen.getByRole('button', { name: 'Run request' }));
    expect(screen.getByRole('dialog', { name: 'Are you sure?' }).textContent).toContain('high risk, not easily reversed');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/request'))).toBe(false);
  });

  it('keeps the form order and drops empty values', () => {
    const tool = { id: 't', group: 'g', label: 'l', risk: 'low' as const, reversible: true, summary: '', fields: [{ key: 'a', label: 'A', kind: 'text' as const, options: [], required: true, hint: '' }, { key: 'b', label: 'B', kind: 'text' as const, options: [], required: false, hint: '' }, { key: 'c', label: 'C', kind: 'text' as const, options: [], required: false, hint: '' }] };
    expect(confirmLines(tool, { c: ' z ', a: 'x', b: '  ' })).toEqual([{ label: 'A', value: 'x' }, { label: 'C', value: 'z' }]);
  });
});
