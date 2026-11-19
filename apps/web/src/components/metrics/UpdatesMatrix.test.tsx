import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { UpdatesMatrix, columnMax } from './UpdatesMatrix';

const ROWS = [
  { engineer: 'Zed', detail: { '2026-11-17': { comments: 4, updated: 2, resolved: 0 } } },
  { engineer: 'Amy', detail: { '2026-11-17': { comments: 8, updated: 6, resolved: 3 } } },
];

afterEach(() => cleanup());

describe('the ticket updates table', () => {
  it('works out the widest value of each week and column across everyone, at least one', () => {
    expect(columnMax(ROWS, ['2026-11-17', '2026-11-24'])).toEqual({ '2026-11-17|comments': 8, '2026-11-17|updated': 6, '2026-11-17|resolved': 3, '2026-11-24|comments': 1, '2026-11-24|updated': 1, '2026-11-24|resolved': 1 });
  });

  it('shows three bars a week per person in name order, each as long as its share of the column', () => {
    render(<UpdatesMatrix weeks={['2026-11-17']} rows={ROWS} />);
    const m = screen.getByTestId('updates-matrix');
    expect(within(m).getByText('November 17')).toBeInTheDocument();
    expect(within(m).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Team Member', 'November 17', 'Comments Added', 'Tickets Updated', 'Tickets Resolved']);
    const rows = within(m).getAllByRole('row').slice(2);
    expect(rows.map((r) => r.textContent)).toEqual(['Amy863', 'Zed420']);
    const zed = within(rows[1]!).getAllByTestId('pill-fill').map((f) => f.style.width);
    expect(zed.map(parseFloat).map((n) => Math.round(n))).toEqual([50, 33, 0]);
  });
});
