import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { UtilBars, UtilMatrix, utilColorBand, utilFill } from './UtilCharts';

afterEach(() => cleanup());

describe('the utilization colors', () => {
  it('puts 95 and over in red, 80 orange, 60 green, 40 blue and the rest purple, at the edges', () => {
    expect([95, 94.9, 80, 79.9, 60, 59.9, 40, 39.9, 0, null].map(utilColorBand)).toEqual(['red', 'orange', 'orange', 'green', 'green', 'blue', 'blue', 'purple', 'purple', 'purple']);
    expect(utilFill(96)).toBe('rgba(239, 83, 80, 0.28)');
  });
});

describe('the utilization bars and matrix', () => {
  it('draws a bar per week in its color with the percentage above it', () => {
    render(<UtilBars points={[{ label: '2026-11-02', value: 96.5 }, { label: '2026-11-09', value: 42 }]} />);
    const bars = screen.getAllByTestId('util-bar');
    expect(bars).toHaveLength(2);
    expect(bars[0]!.style.border).toContain('rgb(239, 83, 80)');
    expect(bars[1]!.style.border).toContain('rgb(66, 165, 245)');
    expect(screen.getByText('96.50%')).toBeInTheDocument();
    expect(screen.getByText('2026-11-09')).toBeInTheDocument();
  });

  it('lists each person by week with colored cells and a dash for a week with no figure', () => {
    render(<UtilMatrix weeks={['2026-11-02', '2026-11-09']} rows={[{ name: 'Ann', by_week: { '2026-11-02': 101.28, '2026-11-09': null } }, { name: 'Bob', by_week: { '2026-11-02': 31.92 } }]} />);
    const m = screen.getByTestId('util-matrix');
    expect(within(m).getByText('Week: 2026-11-09')).toBeInTheDocument();
    const ann = within(m).getByText('Ann').closest('tr')!;
    expect(within(ann).getByText('101.28%').style.border).toContain('rgb(239, 83, 80)');
    expect(within(ann).getByText('—')).toBeInTheDocument();
    expect(within(m).getByText('31.92%').style.border).toContain('rgb(126, 87, 194)');
  });
});
