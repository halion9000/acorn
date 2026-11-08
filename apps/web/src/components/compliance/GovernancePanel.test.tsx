import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { GovernancePanel, dueText } from './GovernancePanel';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
const item = (over = {}) => ({ id: 'i1', kind: 'policy', title: 'Acceptable use', owner: 'Hal', notes: '', interval_days: 365, next_due: '2026-11-20', last_reviewed_at: null, state: 'due soon', days_until: 12, versions: 1, ...over });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/governance' && !init?.method) return json([item(), item({ id: 'i2', kind: 'vendor', title: 'Vendor review: Pax8', state: 'overdue', days_until: -3, next_due: '2026-11-05', versions: 0 })]);
    if (url.endsWith('/versions') && !init?.method) return json([{ version: 1, body: 'The policy text', change_note: 'initial', created_at: '2026-10-01T00:00:00Z' }]);
    return json({});
  });
});

describe('dueText', () => {
  it('says overdue with the days, due today, and due in N days', () => {
    expect(dueText({ state: 'overdue', days_until: -3, next_due: '2026-11-05' })).toBe('3 days overdue (2026-11-05)');
    expect(dueText({ state: 'overdue', days_until: -1, next_due: '2026-11-07' })).toBe('1 day overdue (2026-11-07)');
    expect(dueText({ state: 'due soon', days_until: 0, next_due: '2026-11-08' })).toBe('due today');
    expect(dueText({ state: 'ok', days_until: 30, next_due: '2026-12-08' })).toBe('due in 30 days (2026-12-08)');
  });
});

describe('GovernancePanel', () => {
  it('lists each item with its state and due text, and offers versions only for a policy', async () => {
    render(<GovernancePanel />);
    expect(await screen.findByTestId('gov-i1')).toHaveTextContent('due in 12 days (2026-11-20)');
    expect(screen.getByTestId('gov-i2')).toHaveTextContent('3 days overdue');
    expect(screen.getByTestId('gov-i1')).toHaveTextContent('Versions (1)');
    expect(screen.getByTestId('gov-i2')).not.toHaveTextContent('Versions');
  });

  it('adds an item, marks one reviewed and archives one', async () => {
    const user = userEvent.setup();
    render(<GovernancePanel />);
    await screen.findByTestId('gov-i1');
    await user.type(screen.getByLabelText('Title'), 'Backup policy');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find((c) => c[0] === '/api/v1/governance' && c[1]?.method === 'POST');
      expect(JSON.parse(post![1].body)).toEqual({ kind: 'policy', title: 'Backup policy', owner: '', interval_days: 365 });
    });
    await user.click(screen.getAllByRole('button', { name: 'Reviewed' })[0]!);
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/governance/i1/reviewed', expect.objectContaining({ method: 'POST' })));
    await user.click(screen.getAllByRole('button', { name: 'Archive' })[1]!);
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/governance/i2', expect.objectContaining({ method: 'DELETE' })));
  });

  it('shows a policy\'s versions newest first and saves new text as a new version', async () => {
    const user = userEvent.setup();
    render(<GovernancePanel />);
    await user.click(await screen.findByRole('button', { name: 'Versions (1)' }));
    expect(await screen.findByTestId('gov-versions')).toHaveTextContent('Version 1 · 2026-10-01 · initial');
    await user.type(screen.getByPlaceholderText('Paste the new text of this policy'), 'New words');
    await user.click(screen.getByRole('button', { name: 'Save as a new version' }));
    await waitFor(() => {
      const post = authFetch.mock.calls.find((c) => String(c[0]).endsWith('/versions') && c[1]?.method === 'POST');
      expect(JSON.parse(post![1].body)).toEqual({ body: 'New words' });
    });
  });

  it('says so when nothing is on the calendar, and shows nothing at all when the API refuses or lacks the route', async () => {
    authFetch.mockImplementation(() => json([]));
    const { unmount } = render(<GovernancePanel />);
    expect(await screen.findByTestId('governance-empty')).toBeInTheDocument();
    unmount();
    authFetch.mockImplementation(() => json({ detail: 'no' }, 403));
    render(<GovernancePanel />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('governance')).toBeNull();
  });
});
