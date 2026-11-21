import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { WeeklyComparisonView, netText, podSummary, sortRows, totalOf } from './WeeklyComparisonView';

const line = (over = {}) => ({ days_worked: 5, new: 22, opened_closed: 10, older_closed: 13, closed: 23, net: 1, new_per_day: 4.4, closed_per_day: 4.6, calls_excluded: 3, ...over });
const REPORT = (over = {}) => ({
  received_at: '2026-11-20T00:00:00Z',
  weeks: ['2026-11-09', '2026-11-16'],
  week: '2026-11-16',
  has_detail: true,
  rows: [
    { pod: 'Pod 1', engineer: 'Edgar Panduro', ...line() },
    { pod: 'Pod 2', engineer: 'James Makowsky', ...line({ new: 46, closed: 43, net: -3 }) },
  ],
  total: line({ days_worked: 10, new: 68, closed: 66, net: -2 }),
  ...over,
});
afterEach(() => cleanup());

describe('the Weekly Tech Comparison', () => {
  it('writes a negative net in parentheses', () => {
    expect(netText(-3)).toBe('(3)');
    expect(netText(0)).toBe('0');
    expect(netText(11)).toBe('11');
  });

  it('shows each tech under their pod, the all pods line, and asks for another week', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT()) });
    render(<WeeklyComparisonView />);
    const table = await screen.findByTestId('weekly-comparison');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Pod',
      'Tech',
      'Days worked',
      'New this week',
      'Opened & closed this week',
      'Older tickets closed this week',
      'Closed this week',
      'Net (closed - new)',
      'New per day worked',
      'Closed per day worked',
      'Dialpad calls excluded',
    ]);
    const james = within(table).getByText('James Makowsky').closest('tr')!;
    expect(within(james).getAllByRole('cell').map((c) => c.textContent)).toEqual(['Pod 2', 'James Makowsky', '5', '46', '10', '13', '43', '(3)', '4.4', '4.6', '3']);
    expect(within(screen.getByTestId('weekly-total')).getByText('All pods')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Week'), '2026-11-09');
    expect(authFetch).toHaveBeenLastCalledWith('/api/v1/reports/metrics/weekly-comparison?week=2026-11-09&r=0');
  });

  it('says CORE has not sent the counts when the detail is missing', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT({ has_detail: false })) });
    render(<WeeklyComparisonView />);
    expect(await screen.findByText(/CORE has not sent the weekly ticket counts/)).toBeInTheDocument();
  });
});

describe('sorting and the pod filter', () => {
  const row = (pod: string, engineer: string, over = {}) => ({ pod, engineer, ...line(), ...over });
  it('orders by a column, numbers largest first, a missing rate last, and keeps the order for equal values', () => {
    const rows = [row('Pod 1', 'A', { closed: 5, new_per_day: null }), row('Pod 1', 'B', { closed: 9, new_per_day: 2 }), row('Pod 2', 'C', { closed: 9, new_per_day: 4 })];
    expect(sortRows(rows, 'closed', -1).map((r) => r.engineer)).toEqual(['B', 'C', 'A']);
    expect(sortRows(rows, 'new_per_day', -1).map((r) => r.engineer)).toEqual(['C', 'B', 'A']);
    expect(sortRows(rows, 'engineer', -1).map((r) => r.engineer)).toEqual(['C', 'B', 'A']);
    expect(sortRows(rows, null, 1)).toBe(rows);
  });

  it('says on the filter button what is chosen', () => {
    expect(podSummary(new Set(), 5)).toBe('Pods: all');
    expect(podSummary(new Set(['Pod 1']), 5)).toBe('Pods: Pod 1');
    expect(podSummary(new Set(['Pod 1', 'Pod 2']), 5)).toBe('Pods: 2 of 5');
    expect(podSummary(new Set(['A', 'B']), 2)).toBe('Pods: all');
  });

  it('works the totals of the rows shown, with the per-day rates from them', () => {
    const t = totalOf([row('Pod 1', 'A', { days_worked: 4, new: 8, closed: 12 }), row('Pod 1', 'B', { days_worked: 5, new: 10, closed: 20 })]);
    expect([t.days_worked, t.new, t.closed, t.net, t.new_per_day, t.closed_per_day]).toEqual([9, 18, 32, 14, 2, 3.6]);
  });

  it('sorts when a heading is pressed, and shows only the pods ticked with their own total', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(REPORT()) });
    render(<WeeklyComparisonView />);
    const table = await screen.findByTestId('weekly-comparison');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by New this week' }));
    expect(within(table).getAllByRole('row').slice(1, 3).map((r) => within(r).getAllByRole('cell')[1]!.textContent)).toEqual(['James Makowsky', 'Edgar Panduro']);
    await userEvent.click(screen.getByLabelText('Pod 1'));
    expect(within(table).queryByText('James Makowsky')).toBeNull();
    expect(within(screen.getByTestId('weekly-total')).getByText('Selected pods')).toBeInTheDocument();
    expect(within(screen.getByTestId('weekly-total')).getAllByRole('cell')[3]!.textContent).toBe('22');
    await userEvent.click(screen.getByRole('button', { name: 'Show all pods' }));
    expect(within(table).getByText('James Makowsky')).toBeInTheDocument();
  });
});
