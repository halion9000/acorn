import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { TicketMetricsView, companyFor, monthName, num, waitText } from './TicketMetricsView';

const tickets = (over: Record<string, unknown> = {}) => ({
  received_at: '2026-11-15T10:00:00Z',
  clients: [{ client_id: '5', client_name: 'Acme Dental, Inc.' }, { client_id: '6', client_name: 'Birch Law' }],
  summary: {
    months: ['2026-09', '2026-10'],
    series: [{ month: '2026-09', created: 20, resolved: 18 }, { month: '2026-10', created: 30, resolved: 33 }],
    created: 50,
    resolved: 51,
    created_per_month: 25,
    resolved_per_month: 25.5,
    first_response_minutes: 125,
    by_type: [{ type: 'Incident', tickets: 40 }, { type: 'Alert', tickets: 10 }],
    resolved_by_agent: [{ agent_id: '40', name: 'Dan Kemp', tickets: 49 }],
    open_now: { total: 7, critical: 1, high: 2 },
  },
  ...over,
});
const csat = (over: Record<string, unknown> = {}) => ({
  received_at: '2026-11-15T10:00:00Z',
  companies: ['Acme Dental Inc', 'Birch Law'],
  summary: {
    months: ['2026-09', '2026-10'],
    responses: 20,
    positive: 17,
    neutral: 1,
    negative: 2,
    satisfied_percent: 85,
    trend: [{ month: '2026-10', positive: 9, neutral: 0, negative: 1, total: 10, satisfied_percent: 90 }],
    recent: [{ company: 'Acme Dental Inc', date: '2026-10-20T10:00:00Z', contact: 'Amy', sentiment: 'negative', rating: 'Not good', comment: 'Slow to answer', ticket_id: '5001' }],
  },
  ...over,
});
const answer = (b: unknown, status = 200) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(b) });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => answer(String(url).includes('/csat') ? csat() : tickets()));
});
afterEach(() => cleanup());

describe('the pure parts', () => {
  it('says a wait the way people do', () => {
    expect([waitText(null), waitText(18.4), waitText(125), waitText(60 * 27 + 5)]).toEqual(['—', '18 min', '2 h 5 min', '1 d 3 h']);
    expect([num(null), num(12345), num(25.5, ' a month')]).toEqual(['—', '12,345', '25.5 a month']);
    expect(monthName('2026-10')).toBe('Oct 26');
  });
  it('finds the SimpleSat company for a client by name, ignoring case and punctuation', () => {
    expect(companyFor('Acme Dental, Inc.', ['Acme Dental Inc', 'Birch Law'])).toBe('Acme Dental Inc');
    expect(companyFor('Nobody', ['Acme'])).toBe('');
  });
});

describe('TicketMetricsView', () => {
  it('shows the cards, the monthly series, tickets by type and by engineer, and the satisfaction section', async () => {
    render(<TicketMetricsView />);
    const cards = await screen.findByTestId('ticket-cards');
    expect(cards).toHaveTextContent('50');
    expect(cards).toHaveTextContent('2 h 5 min');
    expect(within(screen.getByTestId('ticket-series')).getAllByText(/\//)).toHaveLength(2);
    expect(screen.getByTestId('ticket-types')).toHaveTextContent('Incident');
    expect(screen.getByTestId('ticket-agents')).toHaveTextContent('Dan Kemp');
    const sat = await screen.findByTestId('csat');
    expect(sat).toHaveTextContent('85%');
    expect(screen.getByTestId('csat-recent')).toHaveTextContent('Slow to answer');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/ticket-metrics?months=3');
  });

  it('asks again for the client and the period chosen, and finds that client on the satisfaction side by name', async () => {
    render(<TicketMetricsView />);
    await screen.findByTestId('ticket-cards');
    await userEvent.selectOptions(screen.getByLabelText('Client'), '5');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/ticket-metrics?months=3&client_id=5'));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(expect.stringContaining('/csat?months=3&company=Acme%20Dental%2C%20Inc.')));
    await userEvent.click(screen.getByRole('button', { name: 'Last 6 months' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/ticket-metrics?months=6&client_id=5'));
  });

  it('says nothing has arrived instead of showing empty cards, and that satisfaction needs SimpleSat', async () => {
    authFetch.mockImplementation((url: string) => answer(String(url).includes('/csat') ? { received_at: null, companies: [], summary: null } : { received_at: null, clients: [], summary: null }));
    render(<TicketMetricsView />);
    expect(await screen.findByTestId('tickets-empty')).toBeInTheDocument();
    expect(await screen.findByTestId('csat-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('ticket-cards')).toBeNull();
  });

  it('says it needs the report permission when the API refuses', async () => {
    authFetch.mockImplementation(() => answer({}, 403));
    render(<TicketMetricsView />);
    expect(await screen.findByText(/need the report permission/)).toBeInTheDocument();
  });
});
