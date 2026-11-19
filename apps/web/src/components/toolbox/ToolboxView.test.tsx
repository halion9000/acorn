import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { ToolboxView } from './ToolboxView';

const catalog = {
  groups: ['Password and security'],
  stage: 's',
  tools: [{ id: 'reset_mfa', group: 'Password and security', label: "Reset a person's MFA", risk: 'high', reversible: false, summary: 'Remove their methods.', fields: [{ key: 'user', label: 'User (email address)' }, { key: 'reason', label: 'Why' }] }],
};

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
      return { ok: true, json: async () => ({ title: "Reset a person's MFA: ann@acme.com", note: 'Nothing has been run.' }), init };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    expect(screen.getByText('high risk, not easily reversed')).toBeTruthy();
    const ask = screen.getByRole('button', { name: 'Ask for approval' }) as HTMLButtonElement;
    expect(ask.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText('User (email address)'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'lost phone');
    expect(ask.disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    expect(ask.disabled).toBe(false);
    await userEvent.click(ask);
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/toolbox/request', expect.objectContaining({ method: 'POST' })));
    const sent = JSON.parse((authFetch.mock.calls.find((c) => String(c[0]).endsWith('/request'))![1] as RequestInit).body as string);
    expect(sent).toEqual({ tool: 'reset_mfa', client_id: 'c1', args: { user: 'ann@acme.com', reason: 'lost phone' } });
    expect((await screen.findByRole('status')).textContent).toContain('waiting for approval');
  });

  it('shows the server reason when a request is refused, and a plain message when the toolbox is not allowed', async () => {
    authFetch.mockImplementation(async (url: string) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
      return { ok: false, status: 422, json: async () => ({ detail: 'Why is needed.' }) };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    await userEvent.type(screen.getByLabelText('User (email address)'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'x');
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.click(screen.getByRole('button', { name: 'Ask for approval' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Why is needed.');
    cleanup();
    authFetch.mockReset();
    authFetch.mockResolvedValue({ ok: false, status: 403 });
    render(<ToolboxView />);
    expect((await screen.findByRole('alert')).textContent).toContain('needs the alerts permission');
  });
});
