import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PodsMatrix, addSums, groupSums, slotsFor, utilBand, utilTip, utilization, weekSums, type PodRow } from './PodsMatrix';

const row = (over: Partial<PodRow>): PodRow => ({ week: '2026-10-26', pod: 'Pod 1', engineer: 'Dan', resolved: 10, created: 12, logged_hours: 30, days_off: 0, holidays: 0, ...over });
const ROWS = [
  row({}),
  row({ week: '2026-11-02' }),
  row({ week: '2026-11-02', engineer: 'Eve', resolved: 4, created: 2, logged_hours: 16, days_off: 8 }),
  row({ week: '2026-11-02', pod: 'Triage', engineer: 'Ann', logged_hours: 10, holidays: 8 }),
];
const WEEKS = ['2026-10-26', '2026-11-02'];

afterEach(() => cleanup());

describe('utilization the way Rewst counts it', () => {
  it('is logged hours over a 40 hour week less time off and holidays, and none when nothing is left to work', () => {
    const s = weekSums(row({ logged_hours: 24, days_off: 8 }))!;
    expect(s.available).toBe(32);
    expect(utilization(s)).toBe(0.75);
    expect(weekSums(row({ days_off: 40 }))).toBeNull();
    expect(weekSums(undefined)).toBeNull();
    expect(addSums([null, null])).toBeNull();
  });

  it('puts 80% and over in high, 50% and over in medium, and the rest and none in low', () => {
    expect([0.8, 0.79, 0.5, 0.49, null].map(utilBand)).toEqual(['high', 'med', 'med', 'low', 'low']);
  });

  it('explains the percentage in the tip', () => {
    expect(utilTip(weekSums(row({ logged_hours: 24, days_off: 8 }))!)).toContain('Utilization 75.0% = 24 / 32');
  });

  it('adds weeks and people together, giving one column per week and a month total', () => {
    const slots = slotsFor(WEEKS);
    expect(slots.map((s) => `${s.month}:${s.week}`)).toEqual(['2026-10:2026-10-26', '2026-10:null', '2026-11:2026-11-02', '2026-11:null']);
    const g = groupSums(ROWS, ['Dan', 'Eve'], slots[2]!, WEEKS)!;
    expect([g.resolved, g.created, g.available, g.logged]).toEqual([14, 14, 72, 46]);
    expect(groupSums(ROWS, ['Dan'], slots[1]!, WEEKS)!.logged).toBe(30);
  });
});

describe('the pods table', () => {
  it('has a three row header, a row per pod and person, coloured utilization and an All Pods total', () => {
    render(<PodsMatrix rows={ROWS} weeks={WEEKS} />);
    const table = screen.getByTestId('pods-matrix');
    expect(within(table).getByText('October 2026')).toBeInTheDocument();
    expect(within(table).getByText('November 2026')).toBeInTheDocument();
    expect(within(table).getAllByText('Month Total')).toHaveLength(2);
    expect(within(table).getAllByText('Utilization')).toHaveLength(4);
    expect(within(table).getByText('Pod 1')).toBeInTheDocument();
    expect(within(table).getByText('Eve')).toBeInTheDocument();
    expect(within(table).getByText('All Pods')).toBeInTheDocument();
    const dan = within(table).getByText('Dan').closest('tr')!;
    expect(within(dan).getAllByText('75.0%').length).toBeGreaterThan(0);
  });

  it('collapses and opens a pod', async () => {
    render(<PodsMatrix rows={ROWS} weeks={WEEKS} />);
    await userEvent.click(screen.getByRole('button', { name: /Pod 1/ }));
    expect(screen.queryByText('Eve')).toBeNull();
    expect(screen.getByText('Ann')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Pod 1/ }));
    expect(screen.getByText('Eve')).toBeInTheDocument();
  });

  it('says so when there is nothing', () => {
    render(<PodsMatrix rows={[]} weeks={[]} />);
    expect(screen.getByText('Nothing in this period.')).toBeInTheDocument();
  });
});
