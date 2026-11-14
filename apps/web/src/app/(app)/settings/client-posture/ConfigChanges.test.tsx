import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { ConfigChanges, transition } from './ConfigChanges';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
const row = (over: Record<string, unknown> = {}) => ({ key: 'mfa_admins', source: 'cipp', status: 'not_met', previous_status: 'met', evidence: '2 admins without MFA', observed_at: '2026-11-12T10:00:00Z', change: 'worsened', ...over });
const labelFor = (source: string, key: string) => `${source}: ${key.replace(/_/g, ' ')}`;

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(() => json({ rows: [row(), row({ key: 'defender', status: 'met', previous_status: 'not_met', change: 'improved', evidence: '' }), row({ key: 'backups', previous_status: null, change: 'added' })] }));
});

describe('ConfigChanges', () => {
  it('says each change in words: what it went from and to, or that the check appeared', () => {
    expect(transition({ previous_status: 'met', status: 'not_met' })).toBe('Met → Not met');
    expect(transition({ previous_status: null, status: 'partly' })).toBe('Partly met');
  });

  it('lists the changes with their kind, the check named for a person, the date and the evidence', async () => {
    render(<ConfigChanges clientId="c1" labelFor={labelFor} />);
    const list = await screen.findByTestId('config-changes-list');
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('worsened');
    expect(items[0]).toHaveTextContent('cipp: mfa admins');
    expect(items[0]).toHaveTextContent('Met → Not met');
    expect(items[0]).toHaveTextContent('2026-11-12');
    expect(items[0]).toHaveTextContent('2 admins without MFA');
    expect(items[2]).toHaveTextContent('added');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/client-posture/c1/check-history?days=30&limit=500');
  });

  it('asks for the period and the kind of change the person picks', async () => {
    render(<ConfigChanges clientId="c1" labelFor={labelFor} />);
    await screen.findByTestId('config-changes-list');
    await userEvent.selectOptions(screen.getByLabelText('Period'), '7');
    await waitFor(() => expect(authFetch).toHaveBeenLastCalledWith('/api/v1/client-posture/c1/check-history?days=7&limit=500'));
    await userEvent.click(screen.getByRole('button', { name: 'worsened' }));
    await waitFor(() => expect(authFetch).toHaveBeenLastCalledWith('/api/v1/client-posture/c1/check-history?days=7&limit=500&change=worsened'));
    expect(screen.getByRole('button', { name: 'worsened' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says so when nothing changed, and shows the reason when the API refuses', async () => {
    authFetch.mockImplementation(() => json({ rows: [] }));
    const { unmount } = render(<ConfigChanges clientId="c1" labelFor={labelFor} />);
    expect(await screen.findByTestId('config-changes-empty')).toHaveTextContent('Nothing changed in this period.');
    unmount();
    authFetch.mockImplementation(() => json({ detail: 'no' }, 500));
    render(<ConfigChanges clientId="c1" labelFor={labelFor} />);
    expect(await screen.findByText('The API answered 500')).toBeTruthy();
  });
});
