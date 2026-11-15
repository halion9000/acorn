import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientSummaryView, nameIn } from './ClientSummaryView';

const tickets = () => ({
  received_at: '2026-11-15T10:00:00Z',
  clients: [{ client_id: '5', client_name: 'Acme Dental, Inc.' }],
  summary: {
    created: 30,
    resolved: 28,
    created_per_month: 10,
    resolved_per_month: 9.3,
    first_response_minutes: 18,
    by_type: [{ type: 'Incident', tickets: 20 }],
    resolved_by_agent: [{ agent_id: '40', name: 'Dan Kemp', tickets: 18 }],
    open_now: { total: 4, critical: 1, high: 2 },
  },
});
const labor = () => ({ summary: { total_hours: 16.5, hours_per_month: 5.5, by_month: [{ month: '2026-10', hours: 6.5 }], by_type: [{ type: 'Remote Support', hours: 12 }] } });
const csat = () => ({
  companies: ['Acme Dental Inc'],
  summary: { responses: 3, positive: 2, neutral: 0, negative: 1, satisfied_percent: 66.7, recent: [{ date: '2026-10-12T10:00:00Z', contact: 'Amy', sentiment: 'negative', rating: 'Not good', comment: 'Slow to answer' }] },
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => answer(url.includes('/labor-hours') ? labor() : url.includes('/csat') ? csat() : tickets()));
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('finds the name a client has in another tool, ignoring case and punctuation', () => {
    expect(nameIn('Acme Dental, Inc.', ['Birch Law', 'Acme Dental Inc'])).toBe('Acme Dental Inc');
    expect(nameIn('Nobody', ['Birch Law'])).toBe('');
  });
});

describe('the Client summary page', () => {
  it('says so when the permission is missing', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<ClientSummaryView />);
    expect(await screen.findByText(/needs the metrics permission/)).toBeTruthy();
  });

  it('says nothing has arrived yet', async () => {
    authFetch.mockImplementation((url: string) => answer(url.includes('/labor-hours') ? { summary: null } : url.includes('/csat') ? { companies: [], summary: null } : { received_at: null, clients: [], summary: null }));
    render(<ClientSummaryView />);
    expect(await screen.findByTestId('summary-empty')).toBeTruthy();
  });

  it('puts tickets, hours and satisfaction for the chosen client on one page, with the comments', async () => {
    render(<ClientSummaryView />);
    await screen.findByTestId('summary-tickets');
    await userEvent.selectOptions(screen.getByLabelText('Client'), '5');
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('labor-hours?months=3&client=Acme%20Dental%2C%20Inc.'))).toBe(true));
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('csat?months=3&company=Acme%20Dental%2C%20Inc.'))).toBe(true);
    expect(screen.getByText(/Client summary: Acme Dental, Inc./)).toBeTruthy();
    expect(within(screen.getByTestId('summary-tickets')).getByText('18 min', { exact: false })).toBeTruthy();
    expect(within(screen.getByTestId('summary-hours')).getByText(/16.5 h in all/)).toBeTruthy();
    expect(within(screen.getByTestId('summary-csat')).getByText('Slow to answer')).toBeTruthy();
  });

  it('says there are no responses when the client has no SimpleSat company of that name', async () => {
    authFetch.mockImplementation((url: string) => answer(url.includes('/labor-hours') ? labor() : url.includes('/csat') ? { companies: ['Birch Law'], summary: { responses: 9, positive: 9, neutral: 0, negative: 0, satisfied_percent: 100, recent: [] } } : tickets()));
    render(<ClientSummaryView />);
    await screen.findByTestId('summary-tickets');
    await userEvent.selectOptions(screen.getByLabelText('Client'), '5');
    await waitFor(() => expect(within(screen.getByTestId('summary-csat')).getByText(/No survey responses/)).toBeTruthy());
  });
});
