import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { LineChart, PeriodPicker, Table, monthsBack, periodQuery, sortValue, sortedRows, usePeriod } from './kit';
import { TicketResolutionView } from './TicketPages';

afterEach(() => cleanup());

describe('sorting values', () => {
  it('reads money, percents and hours as numbers, text as text, and nothing as nothing', () => {
    expect([sortValue('$1,234'), sortValue('12%'), sortValue('3.5 h'), sortValue(7), sortValue('Acme'), sortValue('—'), sortValue('')]).toEqual([1234, 12, 3.5, 7, 'acme', null, null]);
    expect(sortValue(<b>x</b>)).toBeNull();
  });

  it('orders numbers by size and text A to Z, puts empty values last, and keeps the order given when not sorting', () => {
    const rows = [['b', '10'], ['a', '2'], ['c', '—'], ['d', '33']];
    expect(sortedRows(rows, 1, -1).map((r) => r[0])).toEqual(['d', 'b', 'a', 'c']);
    expect(sortedRows(rows, 1, 1).map((r) => r[0])).toEqual(['a', 'b', 'd', 'c']);
    expect(sortedRows(rows, 0, 1).map((r) => r[0])).toEqual(['a', 'b', 'c', 'd']);
    expect(sortedRows(rows, 0, 0)).toBe(rows);
  });
});

describe('Table', () => {
  const rows = [['Acme', '10', '$5'], ['Birch', '2', '$50'], ['Cedar', '33', '$7']];
  const names = (t: HTMLElement) => within(t).getAllByRole('row').slice(1).map((r) => r.querySelector('td')!.textContent);

  it('sorts a column when its heading is pressed: biggest first, then smallest first, then the order given', async () => {
    render(<Table head={['Client', 'Tickets', 'Cost']} rows={rows} testId="t" />);
    const t = screen.getByTestId('t');
    expect(names(t)).toEqual(['Acme', 'Birch', 'Cedar']);
    await userEvent.click(within(t).getByRole('button', { name: /Cost/ }));
    expect(names(t)).toEqual(['Birch', 'Cedar', 'Acme']);
    expect(within(t).getByRole('button', { name: /Cost/ }).closest('th')).toHaveAttribute('aria-sort', 'descending');
    await userEvent.click(within(t).getByRole('button', { name: /Cost/ }));
    expect(names(t)).toEqual(['Acme', 'Cedar', 'Birch']);
    await userEvent.click(within(t).getByRole('button', { name: /Cost/ }));
    expect(names(t)).toEqual(['Acme', 'Birch', 'Cedar']);
    expect(within(t).getByRole('button', { name: /Cost/ }).closest('th')).toHaveAttribute('aria-sort', 'none');
  });

  it('sorts the first column A to Z first, and shows every sortable heading as sortable before any press', async () => {
    render(<Table head={['Client', 'Tickets']} rows={[['Cedar', '1'], ['Acme', '2']]} testId="t" />);
    const t = screen.getByTestId('t');
    expect(within(t).getAllByRole('button').map((b) => b.textContent)).toEqual(['Client ↕', 'Tickets ↕']);
    await userEvent.click(within(t).getByRole('button', { name: /Client/ }));
    expect(names(t)).toEqual(['Acme', 'Cedar']);
  });
});

describe('periods', () => {
  it('writes the address part for the newest months or a custom range', () => {
    expect(periodQuery(6, null)).toBe('months=6');
    expect(periodQuery(6, { start: '2025-01', end: '2025-06' })).toBe('months=6&start=2025-01&end=2025-06');
    expect(monthsBack(new Date(Date.UTC(2026, 1, 10)), 4)).toEqual(['2026-02', '2026-01', '2025-12', '2025-11']);
  });

  function Harness({ onQuery }: { onQuery: (q: string) => void }) {
    const period = usePeriod(3);
    onQuery(period.query);
    return <PeriodPicker period={period} options={[3, 6, 12, 24, 36]} />;
  }

  it('offers Last month, the page periods and a Custom range with a From and a To month', async () => {
    let last = '';
    render(<Harness onQuery={(q) => (last = q)} />);
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Last month', 'Last 3 months', 'Last 6 months', 'Last 12 months', 'Last 24 months', 'Last 36 months', 'Custom range']);
    await userEvent.click(screen.getByRole('button', { name: 'Last month' }));
    expect(last).toBe('months=1');
    expect(screen.queryByLabelText('From month')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    expect(last).toMatch(/^months=1&start=\d{4}-\d{2}&end=\d{4}-\d{2}$/);
    expect(screen.getByLabelText('From month')).toBeInTheDocument();
    expect(screen.getByLabelText('To year')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Last 12 months' }));
    expect(last).toBe('months=12');
    expect(screen.queryByLabelText('From month')).toBeNull();
  });

  it('keeps the range the right way round when one end is moved past the other', async () => {
    let last = '';
    render(<Harness onQuery={(q) => (last = q)} />);
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    const start = /start=(\d{4}-\d{2})&end=(\d{4}-\d{2})/.exec(last)!;
    const earlier = (document.querySelector('select[aria-label="From month"]') as HTMLSelectElement).options;
    expect(earlier.length).toBeGreaterThan(0);
    await userEvent.selectOptions(screen.getByLabelText('To year'), String(Number(start[2]!.slice(0, 4)) - 3));
    const after = /start=(\d{4}-\d{2})&end=(\d{4}-\d{2})/.exec(last)!;
    expect(after[1]! <= after[2]!).toBe(true);
  });
});

describe('LineChart', () => {
  it('shows a value over each point with its label, and breaks the line at a month with no value', () => {
    render(<LineChart points={[{ label: 'Oct 26', value: 4.95 }, { label: 'Nov 26', value: null }, { label: 'Dec 26', value: 8.34 }]} unit="m" />);
    const c = screen.getByTestId('line-chart');
    expect(within(c).getByText('4.95m')).toBeInTheDocument();
    expect(within(c).getByText('8.34m')).toBeInTheDocument();
    expect(within(c).getByText('Nov 26')).toBeInTheDocument();
    expect(c.querySelectorAll('polyline')).toHaveLength(0);
  });
});

const REPORT = {
  received_at: '2026-11-19T10:00:00Z',
  source: 'report',
  months: ['2026-09', '2026-10'],
  available_months: 43,
  members: [{ engineer: 'Dan Kemp', total: 11, by_month: { '2026-09': 7, '2026-10': 4 } }, { engineer: 'Eve Lee', total: 20, by_month: { '2026-09': 20 } }],
  clients: [{ client: 'Acme', total: 15.2, by_month: { '2026-09': 10.2, '2026-10': 5 } }, { client: 'Birch Law', total: 100, by_month: { '2026-10': 100 } }],
  resolution_by_client: [],
};

describe('the Ticket resolution page', () => {
  beforeEach(() => {
    authFetch.mockReset();
    authFetch.mockImplementation(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(REPORT) }));
  });

  it('shows both tables by month with their months and says how many months of data are held', async () => {
    render(<TicketResolutionView />);
    const members = await screen.findByTestId('resolved-by-member');
    expect(within(members).getByText('Dan Kemp')).toBeInTheDocument();
    const clients = screen.getByTestId('resolution-clients-table');
    expect(within(clients).getByText('Birch Law')).toBeInTheDocument();
    expect(within(clients).getAllByRole('columnheader').map((h) => (h.textContent ?? '').replace(/[↕▲▼]/g, '').trim())).toEqual(['Customer', 'Sep 26', 'Oct 26']);
    expect(screen.getByTestId('resolution-showing')).toHaveTextContent('Showing Sep 2026 - Oct 2026 (2 months) - 43 months of data are held');
  });

  it('asks for the month, a number of months or a custom range chosen', async () => {
    render(<TicketResolutionView />);
    await screen.findByTestId('resolved-by-member');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/metrics/ticket-resolution?months=12');
    await userEvent.click(screen.getByRole('button', { name: 'Last month' }));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/metrics/ticket-resolution?months=1');
    await userEvent.click(screen.getByRole('button', { name: 'Custom range' }));
    expect(authFetch.mock.calls.some((c) => /ticket-resolution\?months=1&start=\d{4}-\d{2}&end=\d{4}-\d{2}$/.test(String(c[0])))).toBe(true);
  });
});
