import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { LaborHoursView, hoursText, monthName, widthPercent } from './LaborHoursView';

const body = () => ({
  received_at: '2026-11-15T10:00:00Z',
  summary: {
    months: ['2026-09', '2026-10'],
    total_hours: 20.5,
    hours_per_month: 10.25,
    clients: ['Acme Dental, Inc.', 'Birch Law'],
    by_month: [
      { month: '2026-09', hours: 10 },
      { month: '2026-10', hours: 10.5 },
    ],
    by_agent: [{ agent_id: '40', name: 'Dan Kemp', hours: 18 }, { agent_id: '41', name: 'Vic Cio', hours: 2.5 }],
    by_client: [{ client: 'Acme Dental, Inc.', hours: 16.5 }],
    by_type: [{ type: 'Remote Support', hours: 15 }],
    teams: ['Pod 1'],
    engineers: [
      { name: 'Dan Kemp', team: 'Pod 1', total: 18, by_month: { '2026-09': 8, '2026-10': 10 } },
      { name: 'Vic Cio', team: '', total: 2.5, by_month: { '2026-10': 2.5 } },
    ],
    client_months: [{ client: 'Acme Dental, Inc.', total: 16.5, by_month: { '2026-09': 6.5, '2026-10': 10 } }],
    type_months: [{ type: 'Remote Support', total: 15, by_month: { '2026-09': 5, '2026-10': 10 } }],
  },
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation(() => answer(body()));
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('writes hours, months and bar widths for people', () => {
    expect(hoursText(10.256)).toBe('10.26 h');
    expect(hoursText(null)).toBe('—');
    expect(monthName('2026-10')).toBe('Oct 26');
    expect(widthPercent(5, 20)).toBe(25);
    expect(widthPercent(0.01, 1000)).toBe(1);
    expect(widthPercent(5, 0)).toBe(0);
  });
});

describe('the Labor hours page', () => {
  it('says so when the permission is missing', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<LaborHoursView />);
    expect(await screen.findByText(/need the metrics permission/)).toBeTruthy();
  });

  it('says nothing has arrived yet', async () => {
    authFetch.mockImplementation(() => answer({ received_at: null, summary: null }));
    render(<LaborHoursView />);
    expect(await screen.findByTestId('labor-empty')).toBeTruthy();
  });

  it('shows the hours by month as a chart and engineers, clients and ticket types by month in tables, with a team filter', async () => {
    render(<LaborHoursView />);
    const agents = await screen.findByTestId('by-agent');
    expect(within(agents).getAllByRole('columnheader').map((h) => (h.textContent ?? '').replace(/[↕▲▼]/g, '').trim())).toEqual(['Engineer', 'Team', 'Sep 26', 'Oct 26']);
    expect(within(agents).getByText('Dan Kemp')).toBeTruthy();
    expect(within(agents).getByText('Unknown')).toBeTruthy();
    expect(within(screen.getByTestId('by-month')).getByText('Oct 26')).toBeTruthy();
    expect(within(screen.getByTestId('by-client')).getByText('6.5')).toBeTruthy();
    expect(within(screen.getByTestId('by-type')).getByText('Remote Support')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Team'), 'Pod 1');
    expect(within(screen.getByTestId('by-agent')).queryByText('Vic Cio')).toBeNull();
    expect(within(screen.getByTestId('by-agent')).getByText('Dan Kemp')).toBeTruthy();
  });

  it('asks again for the period and the client the person picks', async () => {
    render(<LaborHoursView />);
    await screen.findByTestId('by-agent');
    await userEvent.click(screen.getByRole('button', { name: 'Last 12 months' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('months=12'))).toBe(true));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'Birch Law');
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('months=12&client=Birch%20Law'))).toBe(true));
  });
});
