import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { AreaChart, axisTop, smoothPath } from './AreaChart';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DialpadView, dialpadCells } from './StaffPages';

const REPORT = {
  received_at: '2026-11-17T00:00:00Z',
  weeks: [
    { week: '2026-11-02', triage_inbound: 0, hours_on_call: 3.5, calls: 11 },
    { week: '2026-11-09', triage_inbound: 0, hours_on_call: 2, calls: 7 },
  ],
  people: [
    { engineer: 'Zed Last', calls: 3, hours: 1, by_week: { '2026-11-09': { calls: 3, hours: 1 } } },
    { engineer: 'Alex Caico', calls: 15, hours: 4.5, by_week: { '2026-11-02': { calls: 11, hours: 3.5 }, '2026-11-09': { calls: 4, hours: 1 } } },
  ],
  engineers: ['Alex Caico', 'Zed Last'],
};

afterEach(() => cleanup());

describe('the chart helpers', () => {
  it('rounds the axis top up to a tidy number', () => {
    expect([0, 0.4, 14, 36.7, 101, 460].map(axisTop)).toEqual([1, 0.5, 20, 50, 200, 500]);
  });

  it('draws a smooth path through every point, starting at the first', () => {
    const d = smoothPath([[0, 10], [50, 0], [100, 20]]);
    expect(d.startsWith('M0.0,10.0')).toBe(true);
    expect(d.match(/C/g)).toHaveLength(2);
    expect(smoothPath([])).toBe('');
  });

  it('shows a dot and a label for each point, with the colour given', () => {
    render(<AreaChart points={[{ label: '2026-11-02', value: 4 }, { label: '2026-11-09', value: 8 }]} color="#06b6d4" testId="c" />);
    const chart = screen.getByTestId('c');
    expect(within(chart).getByText('2026-11-09')).toBeInTheDocument();
    expect(chart.querySelectorAll('span[title]')).toHaveLength(2);
    expect(chart.querySelector('path[stroke="#06b6d4"]')).not.toBeNull();
  });
});

describe('the DialPad page', () => {
  it('fills a week a person has no calls in with zeros', () => {
    expect(dialpadCells({ '2026-11-09': { calls: 3, hours: 1 } }, ['2026-11-02', '2026-11-09'])).toEqual([{ calls: 0, hours: 0 }, { calls: 3, hours: 1 }]);
  });

  it('shows two area charts and a table of calls and hours for every week and person, in name order', async () => {
    authFetch.mockImplementation(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(REPORT) }));
    render(<DialpadView />);
    expect(await screen.findByText('All Teams Calls By Week')).toBeInTheDocument();
    expect(screen.getByText('All Teams Hours On Call By Week')).toBeInTheDocument();
    expect(screen.getByTestId('chart-inbound')).toBeInTheDocument();
    const table = screen.getByTestId('calls-by-person');
    expect(within(table).getAllByText('# of Calls')).toHaveLength(2);
    expect(within(table).getAllByText('Hours')).toHaveLength(2);
    const rows = within(table).getAllByRole('row').slice(2);
    expect(rows.map((r) => r.textContent)).toEqual(['Alex Caico113.50' + '41.00', 'Zed Last' + '00.00' + '31.00']);
  });
});
