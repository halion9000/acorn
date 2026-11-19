import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ScoreBars, shownMetrics, toggleMetric } from './StaffPages';

const ALL = ['Tickets Closed', 'CSAT', 'Utilization'];

afterEach(() => cleanup());

describe('the scorecard metric picker', () => {
  it('shows every metric until some are unticked, and every metric again when the last is ticked back', () => {
    expect(shownMetrics(ALL, null)).toEqual(ALL);
    const one = toggleMetric(ALL, null, 'CSAT');
    expect(one).toEqual(['Tickets Closed', 'Utilization']);
    expect(shownMetrics(ALL, one)).toEqual(['Tickets Closed', 'Utilization']);
    expect(toggleMetric(ALL, one, 'CSAT')).toBeNull();
    expect(toggleMetric(ALL, ['CSAT'], 'Tickets Closed')).toEqual(['Tickets Closed', 'CSAT']);
  });
});

describe('the score bars', () => {
  it('draws a bar a week sized by the score out of five, empty for a week not scored', () => {
    render(<ScoreBars points={[{ label: '2026-11-02', value: 5 }, { label: '2026-11-09', value: 2 }, { label: '2026-11-16', value: null }]} />);
    const bars = screen.getByTestId('score-bars').querySelectorAll('div.rounded-t');
    expect([...bars].map((b) => (b as HTMLElement).style.height)).toEqual(['100%', '40%', '0%']);
    expect(screen.getByText('Nov 9')).toBeInTheDocument();
  });
});
