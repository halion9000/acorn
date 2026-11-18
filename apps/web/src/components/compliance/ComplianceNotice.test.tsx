import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ComplianceNotice, lastLine, parseNoticeEmails, type Notice } from './ComplianceNotice';

const notice = (over: Partial<Notice> = {}): Notice => ({ emails: ['amy@x.com'], webhook_url: null, weekly: false, last_sent_at: null, last_result: null, ...over });
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });
let current: Notice;

beforeEach(() => {
  authFetch.mockReset();
  current = notice();
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return answer((current = { ...current, ...JSON.parse(String(init.body)) }));
    if (init?.method === 'POST') return answer({ sent: true, items: 4, email: 'sent to 1', webhook: 'not asked' });
    return answer(current);
  });
});

describe('the pure parts', () => {
  it('reads addresses from pasted text and words the last send', () => {
    expect(parseNoticeEmails('Amy@x.com, bob@y.org;amy@x.com\nnope  c@d.io')).toEqual(['amy@x.com', 'bob@y.org', 'c@d.io']);
    expect(lastLine(notice())).toBe('It has not been sent yet.');
    expect(lastLine(notice({ last_result: '3 items. E-mail: sent to 1.', last_sent_at: '2026-11-17T09:00:00Z' }))).toBe('Last sent 2026-11-17. 3 items. E-mail: sent to 1.');
    expect(lastLine(notice({ last_result: 'Nothing was waiting, so nothing was sent.' }))).toMatch(/^Not sent yet\. Nothing was waiting/);
  });
});

describe('the weekly notice panel', () => {
  it('shows the saved settings, saves the changed ones with the addresses cleaned, and asks for the client it is showing', async () => {
    render(<ComplianceNotice clientId="c 1" />);
    const box = await screen.findByLabelText(/E-mail addresses/);
    expect(box).toHaveValue('amy@x.com');
    expect(authFetch.mock.calls[0][0]).toBe('/api/v1/compliance/notices?client_id=c%201');
    fireEvent.change(box, { target: { value: 'Bob@Y.org, bob@y.org, nope' } });
    fireEvent.change(screen.getByLabelText(/Web address/), { target: { value: ' https://hooks.example.com/a ' } });
    await userEvent.click(screen.getByLabelText('Send it every week'));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([, i]) => i?.method === 'PUT')).toBe(true));
    const put = authFetch.mock.calls.find(([, i]) => i?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/compliance/notices?client_id=c%201');
    expect(JSON.parse(put[1].body)).toEqual({ emails: ['bob@y.org'], webhook_url: 'https://hooks.example.com/a', weekly: true });
    expect(await screen.findByTestId('notice-note')).toHaveTextContent('Saved.');
  });

  it('shows the reason the server gives when it refuses', async () => {
    authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method === 'PUT' ? answer({ detail: 'The web address must start with https://.' }, 422) : answer(current)));
    render(<ComplianceNotice />);
    await screen.findByLabelText(/Web address/);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('must start with https://');
  });

  it('sends now and says how it went; Send now is not offered until something is saved to send to', async () => {
    render(<ComplianceNotice />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send now' }));
    expect(await screen.findByTestId('notice-note')).toHaveTextContent('Sent: 4 items. E-mail: sent to 1. Web address: not asked.');
    expect(authFetch.mock.calls.some(([u, i]) => u === '/api/v1/compliance/notices/send' && i?.method === 'POST')).toBe(true);
  });

  it('has no Send now when nothing is saved', async () => {
    current = notice({ emails: [] });
    render(<ComplianceNotice />);
    expect(await screen.findByRole('button', { name: 'Send now' })).toBeDisabled();
  });
});
