import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { CustomerExperienceView, MonthlyLicensingView, UserRolesView, recentMonths } from './CustomerPages';
import { barWidth, monthShort, weekLabel } from './kit';
import { DialpadView, PodsView, ScorecardView, StaffHoursView, StaffMetricsView, TicketUpdatesView, gradeClass } from './StaffPages';
import { MonthlyInvoicingView, TicketResolutionView, TicketVolumeView } from './TicketPages';

const W1 = '2026-10-26';
const W2 = '2026-11-02';
const at = '2026-11-15T10:00:00Z';
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

const DATA: Record<string, unknown> = {
  'staff-metrics': { received_at: at, weeks: [{ week: W1, utilization: 45, closed: 32 }, { week: W2, utilization: 40, closed: 9 }], members: [{ engineer: 'Dan', team: 'Pod 1', utilization: 55, closed: 40, labor_hours: 42 }], teams: ['Pod 1', 'Pod 2'] },
  pods: { received_at: at, weeks: [W1], rows: [{ week: W1, pod: 'Pod 1', engineer: 'Dan', resolved: 31, created: 5, logged_hours: 28, days_off: 0, holidays: 0 }], pods: [{ pod: 'Pod 1', engineers: 1, utilization: 55, resolved: 40, created: 7, days_off: 2, holidays: 0, weekly: [{ week: W1, engineers: [{ engineer: 'Dan', utilization: 70, resolved: 31, created: 5, days_off: 0, holidays: 0 }] }] }] },
  'ticket-updates': { received_at: at, weeks: [W1, W2], members: ['Dan', 'Vic'], rows: [{ engineer: 'Dan', total: 32, by_week: { [W1]: 20, [W2]: 12 } }], weekly_total: { [W1]: 20, [W2]: 12 } },
  dialpad: { received_at: at, weeks: [{ week: W1, triage_inbound: 6, hours_on_call: 6, calls: 13 }], people: [{ engineer: 'Dan', calls: 12, hours: 5.5, by_week: { [W1]: { calls: 12, hours: 5.5 } } }], engineers: ['Dan', 'Vic'] },
  'staff-hours': { received_at: at, total_hours: 20.5, types: [{ type: 'Remote Support', hours: 15, share_percent: 73.2 }], people: [{ name: 'Dan Kemp', total: 18, by_type: { 'Remote Support': 15 } }] },
  scorecard: {
    received_at: at,
    metrics: ['Tickets Closed', 'CSAT'],
    weights: { 'Tickets Closed': 3, CSAT: 1 },
    people: [{ engineer: 'Dan', team: 'Pod 1', weeks_scored: 2, average: 3.4, grade: 'B' }],
    detail: { engineer: 'Dan', average: 3.4, grade: 'B', weeks: [{ week: W2, score: 2.5, grade: 'C', factors: { 'Tickets Closed': 2, CSAT: null }, values: {}, days_worked: 3 }, { week: W1, score: null, grade: '-', factors: { 'Tickets Closed': null, CSAT: null }, values: {}, days_worked: 5 }], metric_averages: { 'Tickets Closed': 2, CSAT: null }, trend: [{ week: W1, score: null }, { week: W2, score: 2.5 }] },
  },
  'ticket-resolution': { received_at: at, months: ['2026-10', '2026-11'], members: [{ engineer: 'Dan', total: 40, by_month: { '2026-10': 31, '2026-11': 9 } }], resolution_by_client: [{ client: 'Birch', hours: 10, tickets: 2 }] },
  'ticket-volume': {
    received_at: at,
    months: ['2026-10', '2026-11'],
    total_created: 13,
    by_type: [{ name: 'Incident', total: 11, by_month: { '2026-10': 4, '2026-11': 7 } }],
    by_category: [{ name: 'Email', total: 5, by_month: {} }],
    per_month: [{ month: '2026-10', created: 6 }],
    by_client: [{ client: 'Acme', created: 10 }],
    priority_last_60_days: [{ priority: 'High', created: 6 }],
    stale_by_tech: [{ tech: 'Dan', tickets: 2 }],
    stale: [{ ticket_id: '2', client: 'Birch', agent: 'Dan', title: 'VPN', priority: 'Medium', status: 'New', age_days: 90 }],
    techs: ['Dan'],
  },
  'monthly-invoicing': { received_at: at, months: ['2026-10'], total: 1874, trend: [{ month: '2026-10', amount: 1874 }], by_category: [{ category: 'Managed', amount: 1500 }], clients: [{ client: 'Acme', total: 1764, items: [{ item: 'Managed Services', category: 'Managed', quantity: 1, amount: 1500 }] }] },
  'customer-experience': {
    received_at: at,
    months: ['2026-10'],
    overall: { name: 'All', responses: 5, positive: 2, neutral: 1, negative: 2, csat: 40, neutral_percent: 20, negative_percent: 40 },
    by_company: [{ company: 'Acme', responses: 4, positive: 2, neutral: 1, negative: 1, csat: 50, neutral_percent: 25, negative_percent: 25 }],
    by_member: [{ member: 'Dan', responses: 2, positive: 1, neutral: 1, negative: 0, csat: 50, neutral_percent: 50, negative_percent: 0 }],
    by_month: [{ month: '2026-10', responses: 5, positive: 2, neutral: 1, negative: 2, csat: 40, neutral_percent: 20, negative_percent: 40 }],
    recent: [{ company: 'Acme', date: '2026-10-12T10:00:00Z', contact: 'Amy', sentiment: 'negative', rating: 'Not good', comment: 'Slow to answer', ticket_id: '1' }],
  },
  'monthly-licensing': {
    received_at: at,
    month: '2026-11',
    as_of: 'now',
    items: [{ key: 'm365|Business Premium', source: 'm365', item: 'Business Premium', unit: 'user', total: 17 }, { key: 'ninjaone|Windows workstations', source: 'ninjaone', item: 'Windows workstations', unit: 'device', total: 20 }],
    clients: [{ client_id: 'c1', client: 'Acme', counts: { 'm365|Business Premium': 12, 'ninjaone|Windows workstations': 20 } }, { client_id: 'c2', client: 'Birch', counts: { 'm365|Business Premium': 5 } }],
  },
  'user-roles': {
    received_at: at,
    roles: [{ role: 'Global Administrator', total: 3 }, { role: 'Exchange Administrator', total: 1 }],
    clients: [{ client_id: '5', client: 'Acme', counts: { 'Global Administrator': 2, 'Exchange Administrator': 1 }, members: { 'Global Administrator': [{ name: 'Amy', upn: 'amy@a.example', enabled: true }, { name: 'Bob', upn: 'bob@a.example', enabled: false }] } }],
  },
};
const keyOf = (url: string) => /reports\/metrics\/([a-z-]+)/.exec(url)![1]!;

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    const key = keyOf(url);
    // the scorecard only carries a member's weeks once one is asked for
    if (key === 'scorecard' && !String(url).includes('member=')) return answer({ ...(DATA.scorecard as object), detail: null });
    return answer(DATA[key]);
  });
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('writes weeks, months and bar widths for people', () => {
    expect(weekLabel('2026-11-02')).toBe('Nov 2');
    expect(monthShort('2026-11')).toBe('Nov 26');
    expect(barWidth(5, 20)).toBe(25);
    expect(barWidth(0.001, 1000)).toBe(1);
    expect(barWidth(5, 0)).toBe(0);
    expect(gradeClass('S')).toContain('emerald');
    expect(gradeClass('-')).toContain('gray');
  });
  it('lists the last twelve months newest first', () => {
    const m = recentMonths(new Date(Date.UTC(2026, 10, 15)));
    expect(m).toHaveLength(12);
    expect(m[0]).toBe('2026-11');
    expect(m[2]).toBe('2026-09');
    expect(m[11]).toBe('2025-12');
  });
});

const PAGES: [string, () => React.ReactElement, RegExp][] = [
  ['Staff metrics', () => <StaffMetricsView />, /Weekly Team Metrics/],
  ['Pods', () => <PodsView />, /Metrics by Pods/],
  ['Ticket updates', () => <TicketUpdatesView />, /Ticket Updates by Team Member/],
  ['DialPad', () => <DialpadView />, /DialPad Metrics/],
  ['Staff hours', () => <StaffHoursView />, /Staff hours distribution/],
  ['Scorecard', () => <ScorecardView />, /Service desk scorecard/],
  ['Ticket resolution', () => <TicketResolutionView />, /Ticket resolution time/],
  ['Ticket volume', () => <TicketVolumeView />, /Ticket volume analysis/],
  ['Monthly invoicing', () => <MonthlyInvoicingView />, /Monthly invoicing analysis/],
  ['Customer experience', () => <CustomerExperienceView />, /Customer experience/],
  ['User roles', () => <UserRolesView />, /User roles/],
];

describe.each(PAGES)('%s', (_name, view, title) => {
  it('says what to ask for when the metrics permission is missing', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(view());
    expect(await screen.findByText(/needs the metrics permission/)).toBeTruthy();
  });
  it('says nothing has arrived yet when CORE has sent nothing', async () => {
    authFetch.mockImplementation(() => answer({ received_at: null, weeks: [], months: [], pods: [], members: [], rows: [], people: [], types: [], clients: [], roles: [], by_company: [], by_member: [], by_month: [], recent: [], trend: [], by_category: [], per_month: [], by_type: [], by_client: [], stale: [], stale_by_tech: [], priority_last_60_days: [], techs: [], resolution_by_client: [], engineers: [], teams: [], metrics: [], weights: {}, detail: null, overall: null, total: 0, total_hours: 0, total_created: 0, weekly_total: {} }));
    render(view());
    expect(await screen.findByTestId('nothing-yet')).toBeTruthy();
    expect(screen.getByRole('heading', { name: title })).toBeTruthy();
  });
});

describe('the pages with data', () => {
  it('Staff metrics shows the weekly charts and each member, and asks again for a team', async () => {
    render(<StaffMetricsView />);
    expect(await screen.findByTestId('util-by-week')).toBeTruthy();
    expect(within(screen.getByTestId('util-by-member')).getByText('Dan')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Team'), 'Pod 2');
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('team=Pod%202'))).toBe(true));
  });
  it('Pods lists the pods and their weeks', async () => {
    render(<PodsView />);
    expect(within(await screen.findByTestId('pods-table')).getByText('Pod 1')).toBeTruthy();
    expect(within(screen.getByTestId('pods-matrix')).getByText('Dan')).toBeTruthy();
  });
  it('Ticket updates picks members from a searchable list and asks for the ones picked', async () => {
    render(<TicketUpdatesView />);
    await screen.findByTestId('updates-table');
    await userEvent.click(screen.getByRole('button', { name: /team members/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await userEvent.click(screen.getByLabelText('Vic'));
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('members=Vic'))).toBe(true));
  });
  it('Ticket updates says why when every count is zero, and not otherwise', async () => {
    authFetch.mockImplementation(() => answer({ ...(DATA['ticket-updates'] as object), rows: [{ engineer: 'Dan', total: 0, by_week: {} }], weekly_total: {} }));
    const { unmount } = render(<TicketUpdatesView />);
    expect(await screen.findByTestId('updates-all-zero')).toHaveTextContent('Every count here is zero');
    unmount();
    authFetch.mockImplementation((u: string) => answer(DATA['ticket-updates'] as object));
    render(<TicketUpdatesView />);
    await screen.findByTestId('updates-table');
    expect(screen.queryByTestId('updates-all-zero')).toBeNull();
  });
  it('DialPad shows triage and hours by week and the calls per person', async () => {
    render(<DialpadView />);
    expect(await screen.findByTestId('triage-by-week')).toBeTruthy();
    expect(within(screen.getByTestId('calls-by-person')).getByText('Dan')).toBeTruthy();
  });
  it('Staff hours shows the share of each ticket type', async () => {
    render(<StaffHoursView />);
    expect(within(await screen.findByTestId('hours-by-type')).getByText(/73.2%/)).toBeTruthy();
  });
  it('Scorecard asks for the member chosen and shows their weeks, marking one not scored', async () => {
    render(<ScorecardView />);
    await screen.findByTestId('score-people');
    expect(screen.getByText(/Choose a team member/)).toBeTruthy();
    await userEvent.click(screen.getByLabelText('Dan'));
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('member=Dan'))).toBe(true));
    expect(await screen.findByText(/\(not scored\)/)).toBeTruthy();
    expect(screen.getByTestId('score-trend')).toBeTruthy();
  });
  it('Ticket resolution shows resolved per member and resolution time per client', async () => {
    render(<TicketResolutionView />);
    expect(within(await screen.findByTestId('resolved-by-member')).getByText('Dan')).toBeTruthy();
    expect(within(screen.getByTestId('resolution-by-client')).getByText(/10 h \(2 tickets\)/)).toBeTruthy();
  });
  it('Ticket volume shows the breakdowns and narrows stale tickets to a tech', async () => {
    render(<TicketVolumeView />);
    expect(within(await screen.findByTestId('volume-by-type')).getByText('Incident')).toBeTruthy();
    expect(within(screen.getByTestId('stale-detail')).getByText('VPN')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Tech'), 'Dan');
    expect(within(screen.getByTestId('stale-detail')).getByText('VPN')).toBeTruthy();
  });
  it('Monthly invoicing shows the total and each client line', async () => {
    render(<MonthlyInvoicingView />);
    const clients = await screen.findByTestId('invoicing-clients');
    expect(within(clients).getByText('Acme')).toBeTruthy();
    expect(within(screen.getByTestId('invoicing-category')).getByText('$1,500')).toBeTruthy();
  });
  it('Customer experience shows the breakdowns and the written comment, and filters by sentiment', async () => {
    render(<CustomerExperienceView />);
    expect(within(await screen.findByTestId('exp-company')).getByText('Acme')).toBeTruthy();
    expect(within(screen.getByTestId('exp-doughnut')).getByText(/Positive/)).toBeTruthy();
    expect(screen.getByTestId('exp-by-month-chart')).toBeTruthy();
    expect(within(screen.getByTestId('exp-recent')).getByText('Slow to answer')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Filter by'), 'negative');
    await waitFor(() => expect(authFetch.mock.calls.some(([u]) => String(u).includes('sentiment=negative'))).toBe(true));
  });
  it('Monthly licensing shows a client by item table and hides an item that is unticked', async () => {
    render(<MonthlyLicensingView />);
    const table = await screen.findByTestId('licensing-table');
    expect(within(table).getByText('Windows workstations')).toBeTruthy();
    expect(within(table).getByText('Total')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /items/ }));
    await userEvent.click(screen.getByLabelText(/Windows workstations/));
    expect(within(screen.getByTestId('licensing-table')).queryByText('Windows workstations')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Select all' }));
    expect(within(screen.getByTestId('licensing-table')).getByText('Windows workstations')).toBeTruthy();
  });
  it('Monthly licensing says so when nothing was counted that month', async () => {
    authFetch.mockImplementation(() => answer({ ...(DATA['monthly-licensing'] as object), as_of: '2025-02-01', clients: [], items: [] }));
    render(<MonthlyLicensingView />);
    expect(await screen.findByTestId('licensing-empty')).toBeTruthy();
  });
  it('User roles shows who holds each role and hides a role that is unticked', async () => {
    render(<UserRolesView />);
    const table = await screen.findByTestId('roles-table');
    expect(within(table).getByText('Exchange Administrator')).toBeTruthy();
    expect(screen.getByText(/Bob \(disabled\)/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /roles/ }));
    await userEvent.click(screen.getByLabelText(/Exchange Administrator/));
    expect(within(screen.getByTestId('roles-table')).queryByText('Exchange Administrator')).toBeNull();
  });
});
