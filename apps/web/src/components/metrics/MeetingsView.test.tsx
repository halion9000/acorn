import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { MeetingsView } from './MeetingsView';

const REPORT = {
  received_at: '2026-11-18T00:00:00Z',
  weeks: ['2026-11-02', '2026-11-09'],
  total_hours: 6.75,
  by_week: [{ week: '2026-11-02', hours: 3.5 }, { week: '2026-11-09', hours: 3.25 }],
  people: [{ engineer: 'Ann', team: 'Pod 1', total: 5.5, by_week: { '2026-11-02': 3.5, '2026-11-09': 2 } }, { engineer: 'Bob', team: 'Unassigned', total: 1.25, by_week: { '2026-11-09': 1.25 } }],
  by_team: [{ team: 'Pod 1', hours: 5.5 }, { team: 'Unassigned', hours: 1.25 }],
  teams: ['Pod 1', 'Unassigned'],
};

afterEach(() => cleanup());

describe('the Meetings page', () => {
  it('shows the total with a weekly chart, each person by week and the total for each team', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<MeetingsView />);
    expect(await screen.findByText('Total meeting hours: 6.8')).toBeInTheDocument();
    expect(screen.getByTestId('meetings-chart')).toBeInTheDocument();
    const people = screen.getByTestId('meetings-people');
    expect(within(people).getAllByRole('columnheader').map((h) => (h.textContent ?? '').replace(/[↕▲▼]/g, '').trim())).toEqual(['User Name', 'Team', 'Total', '2026-11-02', '2026-11-09']);
    expect(within(people).getByText('Bob')).toBeInTheDocument();
    expect(within(screen.getByTestId('meetings-teams')).getByText('Pod 1')).toBeInTheDocument();
  });

  it('asks again for the team chosen', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT) });
    render(<MeetingsView />);
    await screen.findByTestId('meetings-people');
    await userEvent.selectOptions(screen.getByLabelText('Team'), 'Pod 1');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).includes('&team=Pod%201'))).toBe(true));
  });

  it('says nothing has arrived when CORE has sent nothing', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ received_at: null, weeks: [], total_hours: 0, by_week: [], people: [], by_team: [], teams: [] }) });
    render(<MeetingsView />);
    expect(await screen.findByText(/meeting hours/i)).toBeInTheDocument();
  });
});
