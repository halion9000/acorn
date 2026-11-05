import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));
vi.mock('react-hot-toast', () => ({ default: toast }));

import { CredentialReminders, daysLeftText, isReminderList } from './CredentialReminders';

const reply = (body: unknown, ok = true) => ({ ok, json: () => Promise.resolve(body) });

beforeEach(() => {
  authFetch.mockReset();
  toast.error.mockReset();
});

describe('daysLeftText', () => {
  it('reads in plain words, past and future', () => {
    expect(daysLeftText(12)).toBe('in 12 days');
    expect(daysLeftText(1)).toBe('in 1 day');
    expect(daysLeftText(0)).toBe('today');
    expect(daysLeftText(-3)).toBe('expired 3 days ago');
    expect(daysLeftText(-1)).toBe('expired 1 day ago');
    expect(daysLeftText(undefined)).toBe('');
  });
});

describe('CredentialReminders', () => {
  it('lists what is tracked with the days left', async () => {
    authFetch.mockResolvedValue(reply({ entries: [{ name: 'Entra secret', expires_on: '2026-11-10', days_left: 5 }] }));
    render(<CredentialReminders />);
    const row = await screen.findByTestId('reminder-row');
    expect(row).toHaveTextContent('Entra secret');
    expect(row).toHaveTextContent('2026-11-10 (in 5 days)');
  });

  it('adds a reminder by sending the whole list, and shows the saved list', async () => {
    authFetch.mockResolvedValueOnce(reply({ entries: [{ name: 'A', expires_on: '2027-01-01', days_left: 57 }] }));
    render(<CredentialReminders />);
    await screen.findByTestId('reminder-row');
    authFetch.mockResolvedValueOnce(reply({ entries: [{ name: 'A', expires_on: '2027-01-01', days_left: 57 }, { name: 'B cert', expires_on: '2027-03-01', days_left: 115 }] }));
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Name'), 'B cert');
    await user.type(screen.getByLabelText('Expires'), '2027-03-01');
    await user.click(screen.getByRole('button', { name: 'Add reminder' }));
    await waitFor(() => expect(screen.getAllByTestId('reminder-row')).toHaveLength(2));
    const [url, init] = authFetch.mock.calls[1]!;
    expect(url).toBe('/api/v1/platform/credential-expiries');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ entries: [{ name: 'A', expires_on: '2027-01-01' }, { name: 'B cert', expires_on: '2027-03-01' }] });
  });

  it('removes one by sending the list without it', async () => {
    authFetch.mockResolvedValueOnce(reply({ entries: [{ name: 'A', expires_on: '2027-01-01' }, { name: 'B', expires_on: '2027-02-01' }] }));
    render(<CredentialReminders />);
    await screen.findAllByTestId('reminder-row');
    authFetch.mockResolvedValueOnce(reply({ entries: [{ name: 'B', expires_on: '2027-02-01' }] }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Stop tracking A' }));
    await waitFor(() => expect(screen.getAllByTestId('reminder-row')).toHaveLength(1));
    expect(JSON.parse(authFetch.mock.calls[1]![1].body)).toEqual({ entries: [{ name: 'B', expires_on: '2027-02-01' }] });
  });

  it('says what the server refused and keeps the list as it was', async () => {
    authFetch.mockResolvedValueOnce(reply({ entries: [{ name: 'A', expires_on: '2027-01-01' }] }));
    render(<CredentialReminders />);
    await screen.findByTestId('reminder-row');
    authFetch.mockResolvedValueOnce(reply({ detail: 'A is listed twice.' }, false));
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Name'), 'a');
    await user.type(screen.getByLabelText('Expires'), '2027-05-01');
    await user.click(screen.getByRole('button', { name: 'Add reminder' }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('A is listed twice.'));
    expect(screen.getAllByTestId('reminder-row')).toHaveLength(1);
  });

  it('shows nothing when the account may not read it, or the answer is not this view', async () => {
    authFetch.mockResolvedValueOnce(reply({ detail: 'forbidden' }, false));
    const a = render(<CredentialReminders />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('credential-reminders')).toBeNull();
    a.unmount();
    authFetch.mockResolvedValueOnce(reply({ overall: 'ok' }));
    render(<CredentialReminders />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('credential-reminders')).toBeNull();
  });

  it('recognises only a list of name and date', () => {
    expect(isReminderList({ entries: [] })).toBe(true);
    expect(isReminderList({ entries: [{ name: 'A' }] })).toBe(false);
    expect(isReminderList(null)).toBe(false);
  });
});
