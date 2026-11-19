import { describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MonthYearPicker, monthForYear, monthName, monthsOfYear, yearsOf } from './MonthYearPicker';

const MONTHS = ['2023-11', '2023-12', '2024-01', '2024-02', '2024-03', '2025-01', '2025-02', '2026-10', '2026-11'];

describe('the helpers', () => {
  it('lists the years that have data newest first and the months of one year January first', () => {
    expect(yearsOf(MONTHS)).toEqual(['2026', '2025', '2024', '2023']);
    expect(monthsOfYear(['2024-03', '2024-01', '2025-01'], '2024')).toEqual(['2024-01', '2024-03']);
    expect(monthName('2026-10')).toBe('October');
  });

  it('keeps the same month when the new year has it and otherwise takes the newest month that year has', () => {
    expect(monthForYear(MONTHS, '2026-01', '2025')).toBe('2025-01');
    expect(monthForYear(MONTHS, '2026-10', '2025')).toBe('2025-02');
    expect(monthForYear(MONTHS, '2025-02', '2023')).toBe('2023-12');
  });
});

describe('MonthYearPicker', () => {
  it('shows a Month and a Year dropdown, with only the months of the chosen year', () => {
    render(<MonthYearPicker months={MONTHS} value="2024-02" onChange={() => {}} />);
    const month = screen.getByLabelText('Month') as HTMLSelectElement;
    const year = screen.getByLabelText('Year') as HTMLSelectElement;
    expect(Array.from(year.options).map((o) => o.textContent)).toEqual(['2026', '2025', '2024', '2023']);
    expect(Array.from(month.options).map((o) => o.textContent)).toEqual(['January', 'February', 'March']);
    expect(month.value).toBe('2024-02');
    expect(year.value).toBe('2024');
  });

  it('reports a month as YYYY-MM when one is picked, and moves to the same month of another year when the year changes', async () => {
    const change = vi.fn();
    render(<MonthYearPicker months={MONTHS} value="2024-02" onChange={change} />);
    await userEvent.selectOptions(screen.getByLabelText('Month'), '2024-03');
    expect(change).toHaveBeenLastCalledWith('2024-03');
    await userEvent.selectOptions(screen.getByLabelText('Year'), '2025');
    expect(change).toHaveBeenLastCalledWith('2025-02');
    cleanup();
    render(<MonthYearPicker months={MONTHS} value="2024-01" onChange={change} />);
    await userEvent.selectOptions(screen.getByLabelText('Year'), '2025');
    expect(change).toHaveBeenLastCalledWith('2025-01');
    await userEvent.selectOptions(screen.getByLabelText('Year'), '2026');
    expect(change).toHaveBeenLastCalledWith('2026-11');
  });
});
