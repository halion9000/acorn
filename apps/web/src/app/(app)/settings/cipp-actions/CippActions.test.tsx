import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CippActions, clientLabel, modeSentence, noteFor, wouldSentence, type ActionsReport, type ActionsView, type AuditEntry } from './CippActions';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

const json = (data: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(data) });

const report = (over: Partial<ActionsReport> = {}): ActionsReport => ({
  live: false,
  all_clients: false,
  clients: ['cipp-1', 'cipp-9'],
  protected_users: 2,
  protected_domains: 1,
  max_per_hour: 5,
  actions: [
    { action: 'revoke_sessions', risk: 'low', reversible: true, summary: 'Sign the person out everywhere' },
    { action: 'contain_user', risk: 'high', reversible: false, summary: 'Contain a compromised account' },
  ],
  audit: [
    { at: '2026-10-29T10:00:00Z', action: 'revoke_sessions', client_id: 'cipp-1', user: 'amy@acme.com', actor: 'playbook', reason: 'alert a1', result: 'dry_run', code: null, detail: null, would_refuse: 'client_not_opted_in' },
    { at: '2026-10-29T09:00:00Z', action: 'contain_user', client_id: 'cipp-2', user: 'bob@acme.com', actor: null, reason: null, result: 'refused', code: 'protected', detail: null, would_refuse: null },
    { at: '2026-10-29T08:00:00Z', action: 'revoke_sessions', client_id: 'cipp-1', user: 'cy@acme.com', actor: 'playbook', reason: 'alert a2', result: 'executed', code: null, detail: 'CIPP accepted it', would_refuse: null },
  ],
  ...over,
});

const view = (r: ActionsReport | null, receivedAt = new Date().toISOString()): ActionsView => ({ report: r, received_at: r ? receivedAt : null, client_names: { 'cipp-1': 'Pirkey Barber' } });

beforeEach(() => {
  authFetch.mockReset();
});
afterEach(() => cleanup());

describe('the sentences', () => {
  it('say plainly whether real actions are off, on for some clients, on for none, or on for all', () => {
    expect(modeSentence(report())).toBe('Real actions are OFF: every request CORE receives is a dry run, and nothing is sent to CIPP.');
    expect(modeSentence(report({ live: true }))).toBe('Real actions are ON for 2 opted-in clients, at most 5 per client per hour.');
    expect(modeSentence(report({ live: true, clients: ['x'] }))).toContain('1 opted-in client,');
    expect(modeSentence(report({ live: true, clients: [] }))).toContain('NO client');
    expect(modeSentence(report({ live: true, all_clients: true }))).toContain('ALL clients');
  });
  it('say when the cap is 0, that every real request is refused', () => {
    expect(modeSentence(report({ live: true, max_per_hour: 0 }))).toBe('Real actions are ON for 2 opted-in clients, but the hourly cap is 0, so every real request is refused.');
  });
  it('say what would happen if they were switched on', () => {
    expect(wouldSentence(report())).toBe('Switched on, an action could run for only the 2 opted-in clients, at most 5 per client per hour, and never on the 3 protected accounts and domains.');
    expect(wouldSentence(report({ all_clients: true, protected_users: 1, protected_domains: 0 }))).toContain('any client');
    expect(wouldSentence(report({ clients: [] }))).toContain('no client (none is opted in)');
  });
  it('name a client by its mapped name with the id, or by the id alone, and explain a refusal or a dry run', () => {
    expect(clientLabel('cipp-1', { 'cipp-1': 'Pirkey Barber' })).toBe('Pirkey Barber (cipp-1)');
    expect(clientLabel('cipp-2', {})).toBe('cipp-2');
    const e = (over: Partial<AuditEntry>): AuditEntry => ({ ...report().audit[0], ...over });
    expect(noteFor(e({ result: 'refused', code: 'rate_cap' }))).toBe('Refused: rate cap');
    expect(noteFor(e({ result: 'dry_run', would_refuse: 'client_not_opted_in' }))).toBe('Would have been refused: client not opted in');
    expect(noteFor(e({ result: 'executed', detail: 'CIPP accepted it', would_refuse: null }))).toBe('CIPP accepted it');
  });
});

describe('CippActions', () => {
  it('says CORE has not reported when there is no report yet', async () => {
    authFetch.mockResolvedValue(json(view(null)));
    render(<CippActions />);
    expect(await screen.findByTestId('no-report')).toHaveTextContent('CORE has not reported yet');
  });

  it('shows the mode, the rules with client names, the allowlist with risk, and the audit lines with their outcome', async () => {
    authFetch.mockResolvedValue(json(view(report())));
    render(<CippActions />);
    expect(await screen.findByTestId('mode')).toHaveTextContent('Real actions are OFF');
    expect(screen.getByTestId('opted-in')).toHaveTextContent('Pirkey Barber (cipp-1), cipp-9');
    expect(screen.getByTestId('would')).toHaveTextContent('only the 2 opted-in clients');
    const allow = screen.getByTestId('allowlist');
    expect(allow).toHaveTextContent('revoke_sessions');
    expect(within(allow).getByText('high')).toBeInTheDocument();
    expect(allow).toHaveTextContent('in one step');
    const audit = screen.getByTestId('audit');
    expect(within(audit).getAllByRole('row')).toHaveLength(4);
    expect(audit).toHaveTextContent('Pirkey Barber');
    expect(audit).toHaveTextContent('Would have been refused: client not opted in');
    expect(audit).toHaveTextContent('Refused: protected');
    expect(audit).toHaveTextContent('Executed');
    expect(screen.queryByTestId('stale')).toBeNull();
  });

  it('warns in red when real actions are on, and that CORE has been silent for a while', async () => {
    authFetch.mockResolvedValue(json(view(report({ live: true, all_clients: true }), new Date(Date.now() - 5 * 3_600_000).toISOString())));
    render(<CippActions />);
    expect(await screen.findByTestId('mode')).toHaveTextContent('Real actions are ON for ALL clients');
    expect(screen.getByTestId('mode').className).toMatch(/red/);
    expect(screen.getByTestId('stale')).toHaveTextContent('CORE may not be running');
  });

  it('warns in red when CORE could not write audit lines, and says nothing when it could', async () => {
    authFetch.mockResolvedValue(json(view(report({ audit_failures: 3 }))));
    const first = render(<CippActions />);
    expect(await screen.findByTestId('audit-failures')).toHaveTextContent('CORE could not write 3 audit lines');
    first.unmount();
    authFetch.mockResolvedValue(json(view(report())));
    render(<CippActions />);
    await screen.findByTestId('mode');
    expect(screen.queryByTestId('audit-failures')).toBeNull();
  });

  it('narrows the audit to one outcome and says when none has it', async () => {
    authFetch.mockResolvedValue(json(view(report())));
    const user = userEvent.setup();
    render(<CippActions />);
    await screen.findByTestId('audit');
    await user.selectOptions(screen.getByLabelText('Outcome'), 'executed');
    expect(within(screen.getByTestId('audit')).getAllByRole('row')).toHaveLength(2);
    await user.selectOptions(screen.getByLabelText('Outcome'), 'failed');
    expect(screen.queryByTestId('audit')).toBeNull();
    expect(screen.getByText('No request has that outcome.')).toBeInTheDocument();
  });

  it('says plainly when nothing has been asked yet, and when the page is refused', async () => {
    authFetch.mockResolvedValue(json(view(report({ audit: [] }))));
    const first = render(<CippActions />);
    expect(await screen.findByText('CORE has not been asked to do anything yet.')).toBeInTheDocument();
    first.unmount();
    authFetch.mockResolvedValue(json({}, 403));
    render(<CippActions />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this page.');
  });
});
