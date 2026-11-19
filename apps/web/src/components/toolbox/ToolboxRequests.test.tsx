import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { ToolboxView, stillOpen, type RunItem } from './ToolboxView';

const item = (over: Partial<RunItem>): RunItem => ({ request_id: 'r1', label: 'Reset a different MFA', client: 'Acme', person: 'ann@acme.com', status: 'done', message: null, ticket: null, steps: [], requested_by: 'tech', created_at: null, ...over });
const f = (key: string, label: string, kind: string, required = true) => ({ key, label, kind, options: [], required, hint: '' });
const MFA = { id: 'reset_mfa', group: 'Security', label: 'Reset a person\'s MFA', risk: 'high', reversible: false, summary: 'Remove methods.', fields: [f('ticket', 'Ticket number', 'ticket', false), f('user', 'Person', 'user'), f('reason', 'Why', 'text')] };

beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
  listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme' }]);
});
afterEach(() => cleanup());

describe('recent requests', () => {
  it('knows whether any request is still on its way', () => {
    expect(stillOpen([item({ status: 'done' }), item({ status: 'failed' })])).toBe(false);
    expect(stillOpen([item({ status: 'done' }), item({ status: 'running' })])).toBe(true);
    expect(stillOpen([item({ status: 'waiting' })])).toBe(true);
  });

  it('lists each request with its state, CORE message, ticket and steps', async () => {
    const list = [item({ message: 'Reset the MFA.', ticket: '4711', steps: [{ step: 'Reset MFA methods', ok: true }, { step: 'Write the ticket', ok: false }] }), item({ request_id: 'r2', status: 'failed', label: 'Change a password', message: 'CIPP refused' })];
    authFetch.mockImplementation(async (url: string) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => ({ groups: ['Security'], stage: 's', tools: [MFA] }) };
      if (url.endsWith('/toolbox/requests')) return { ok: true, json: async () => ({ requests: list }) };
      return { ok: true, json: async () => ({}) };
    });
    render(<ToolboxView />);
    const panel = await screen.findByTestId('recent-requests');
    expect(within(panel).getByText('Done')).toBeInTheDocument();
    expect(within(panel).getByText('Failed')).toBeInTheDocument();
    expect(within(panel).getByText('Reset the MFA.')).toBeInTheDocument();
    expect(within(panel).getByText('Ticket 4711')).toBeInTheDocument();
    expect(within(panel).getByText('✓ Reset MFA methods')).toBeInTheDocument();
    expect(within(panel).getByText('✗ Write the ticket')).toBeInTheDocument();
  });

  it('asks again for the list after a request is made', async () => {
    authFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/tools')) return { ok: true, json: async () => ({ groups: ['Security'], stage: 's', tools: [MFA] }) };
      if (url.includes('/lookups')) return { ok: true, json: async () => ({ people: [], domains: [] }) };
      if (url.endsWith('/toolbox/request') && init?.method === 'POST') return { ok: true, json: async () => ({ title: 'Reset MFA: ann@acme.com', note: 'Queued.' }) };
      return { ok: true, json: async () => ({ requests: [] }) };
    });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Reset a person's MFA/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Person'), 'ann@acme.com');
    await userEvent.type(screen.getByLabelText('Why'), 'lost phone');
    await userEvent.click(screen.getByRole('button', { name: 'Run request' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, run it' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Queued.'));
    const asked = authFetch.mock.calls.filter((c) => String(c[0]).endsWith('/toolbox/requests')).length;
    expect(asked).toBeGreaterThanOrEqual(2);
  });
});
