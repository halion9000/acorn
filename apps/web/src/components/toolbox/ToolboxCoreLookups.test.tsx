import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { ToolboxView, badRuleNames, toggleRule } from './ToolboxView';

const f = (key: string, label: string, kind: string, required = true) => ({ key, label, kind, options: [], required, hint: '' });
const catalog = {
  groups: ['User management', 'Mail and permissions'],
  stage: 's',
  tools: [
    { id: 'group_membership', group: 'User management', label: 'Change group membership', risk: 'medium', reversible: true, summary: 'Add or remove.', fields: [f('user', 'Person', 'user'), f('group', 'Group', 'group')] },
    { id: 'remove_inbox_rules', group: 'Mail and permissions', label: 'Remove bad inbox rules', risk: 'medium', reversible: false, summary: 'Remove chosen rules.', fields: [f('user', 'Mailbox', 'user'), f('rules', 'Rules to remove', 'rules'), f('reason', 'Why', 'text', false)] },
  ],
};
const lookups = { people: [{ email: 'ann@acme.com', name: 'Ann Lee', enabled: true, guest: false }], domains: ['acme.com'] };
const rules = [
  { name: 'Forward all', rule_id: 'r1', enabled: true, forwards_to: 'x@evil.net', deletes: false, moves_to: null, suspicious: true, reasons: ['sends mail outside the client (x@evil.net)'] },
  { name: 'Tidy', rule_id: 'r2', enabled: true, forwards_to: null, deletes: false, moves_to: 'Projects', suspicious: false, reasons: [] },
];

function serve(over: { groupsReply?: unknown; rulesReply?: unknown } = {}) {
  authFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/tools')) return { ok: true, json: async () => catalog };
    if (url.includes('/lookups')) return { ok: true, json: async () => lookups };
    if (url.endsWith('/toolbox/groups') && init?.method === 'POST') return { ok: true, json: async () => over.groupsReply ?? { request_id: 'g1', status: 'done', kind: 'groups', result: { groups: [{ name: 'Sales', kind: 'Security', mail: null }, { name: 'Finance', kind: 'Microsoft 365', mail: null }] } } };
    if (url.endsWith('/toolbox/inbox-rules') && init?.method === 'POST') return { ok: true, json: async () => over.rulesReply ?? { request_id: 'q1', status: 'done', kind: 'rules', result: { rules } } };
    return { ok: true, json: async () => ({ title: 'x' }) };
  });
}

beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
  listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme' }]);
});
afterEach(() => cleanup());

describe('the group picker', () => {
  it('reads the clients groups through CORE once the client is chosen and offers them by name', async () => {
    serve();
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Change group membership/ }));
    expect(screen.getByTestId('groups-status').textContent).toContain('Pick a client');
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await waitFor(() => expect(screen.getByTestId('groups-status').textContent).toContain('2 groups.'));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/toolbox/groups', expect.objectContaining({ method: 'POST', body: JSON.stringify({ client_id: 'c1' }) }));
    expect(Array.from(document.querySelectorAll('#groups-group option')).map((o) => o.getAttribute('value'))).toEqual(['Sales', 'Finance']);
    expect(document.querySelector('#groups-group option[value="Sales"]')!.getAttribute('label')).toBe('Security');
  });

  it('says so and lets the name be typed when CORE cannot read the groups', async () => {
    serve({ groupsReply: { request_id: 'g1', status: 'failed', kind: 'groups', message: 'CIPP is not connected in CORE.' } });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Change group membership/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await waitFor(() => expect(screen.getByTestId('groups-status').textContent).toContain('CIPP is not connected in CORE. Type the name instead.'));
    await userEvent.type(screen.getByLabelText('Group'), 'Sales team');
    expect((screen.getByLabelText('Group') as HTMLInputElement).value).toBe('Sales team');
  });
});

describe('the inbox rules picker', () => {
  it('lists the persons rules once the mailbox is picked, ticks the bad ones, and sends only the ticked names', async () => {
    serve();
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Remove bad inbox rules/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    expect(screen.getByText('Pick the mailbox above to see its rules.')).toBeTruthy();
    expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/inbox-rules'))).toBe(false);
    await userEvent.type(screen.getByLabelText('Mailbox'), 'ann@acme.com');
    const bad = await screen.findByRole('checkbox', { name: /Forward all/ });
    expect((bad as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: /Tidy/ }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(/sends mail outside the client/)).toBeTruthy();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/toolbox/inbox-rules', expect.objectContaining({ body: JSON.stringify({ client_id: 'c1', user: 'ann@acme.com' }) }));
    await userEvent.click(screen.getByRole('button', { name: 'Save request' }));
    expect(screen.getByRole('dialog').textContent).toContain('Forward all');
    expect(screen.getByRole('dialog').textContent).not.toContain('Tidy');
    await userEvent.click(screen.getByRole('button', { name: 'Yes, save it' }));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).endsWith('/request'))).toBe(true));
    const sent = JSON.parse((authFetch.mock.calls.find((c) => String(c[0]).endsWith('/request'))![1] as RequestInit).body as string);
    expect(sent).toEqual({ tool: 'remove_inbox_rules', client_id: 'c1', args: { user: 'ann@acme.com', rules: 'Forward all' } });
  });

  it('cannot be sent with no rule ticked, and shows the reason when CORE could not read the rules', async () => {
    serve({ rulesReply: { request_id: 'q1', status: 'failed', kind: 'rules', message: 'The inbox rules could not be read: CIPP returned 500' } });
    render(<ToolboxView />);
    await userEvent.click(await screen.findByRole('button', { name: /Remove bad inbox rules/ }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c1');
    await userEvent.type(screen.getByLabelText('Mailbox'), 'ann@acme.com');
    expect(await screen.findByText(/The rules could not be read: The inbox rules could not be read/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Save request' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('helpers', () => {
  it('ticks the rules that look bad and toggles one name in a list of names', () => {
    expect(badRuleNames(rules)).toBe('Forward all');
    expect(toggleRule('', 'A')).toBe('A');
    expect(toggleRule('A\nB', 'A')).toBe('B');
    expect(toggleRule('A', 'B')).toBe('A\nB');
  });
});
