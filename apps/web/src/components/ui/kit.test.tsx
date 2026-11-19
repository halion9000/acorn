import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BarCell, EmptyState, PageHeader, Segmented, Skeleton, SkeletonRows, Sparkline, StatCard } from './kit';

describe('StatCard', () => {
  it('shows the value, the change with an arrow and a sign, and says better or worse in words', () => {
    render(<StatCard label="First response" value="14 h" delta={-12.5} upIsGood={false} note="on average" />);
    expect(screen.getByTestId('stat-value').textContent).toBe('14 h');
    const d = screen.getByTestId('stat-delta');
    expect(d.textContent).toContain('−12.5%');
    expect(d.textContent).toContain('▼');
    expect(d.textContent).toContain('(better)');
    expect(screen.getByText('on average')).toBeTruthy();
  });
  it('reads an increase of a bad thing as worse, shows no change line without a delta, and a skeleton while loading', () => {
    const { rerender } = render(<StatCard label="Open" value="5" delta={4} upIsGood={false} />);
    expect(screen.getByTestId('stat-delta').textContent).toContain('(worse)');
    rerender(<StatCard label="Open" value="5" />);
    expect(screen.queryByTestId('stat-delta')).toBeNull();
    rerender(<StatCard label="Open" value="5" loading />);
    expect(screen.queryByTestId('stat-value')).toBeNull();
    expect(screen.getByTestId('skeleton')).toBeTruthy();
  });
  it('becomes a button when it has a click handler', async () => {
    const click = vi.fn();
    render(<StatCard label="Critical" value="3" onClick={click} />);
    await userEvent.click(screen.getByRole('button', { name: /Critical/ }));
    expect(click).toHaveBeenCalled();
  });
});

describe('Sparkline', () => {
  it('draws a line with a text description, and nothing for fewer than two points', () => {
    const { container, rerender } = render(<Sparkline values={[1, 3, 2, 5]} label="Tickets" />);
    expect(screen.getByRole('img', { name: 'Tickets' })).toBeTruthy();
    expect(container.querySelector('polyline')?.getAttribute('points')?.split(' ').length).toBe(4);
    expect(container.querySelector('desc')?.textContent).toBe('From 1 to 5');
    rerender(<Sparkline values={[1]} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});

describe('BarCell', () => {
  it('draws the bar as a share of the largest value and keeps the text', () => {
    const { container } = render(<BarCell value={25} max={100} text="25%" tone="good" />);
    expect(screen.getByText('25%')).toBeTruthy();
    expect((container.querySelector('[aria-hidden]') as HTMLElement).style.width).toBe('25%');
  });
  it('draws no bar for a missing value or a zero maximum, and caps at the full width', () => {
    const { container, rerender } = render(<BarCell value={null} max={100} text="n/a" />);
    expect((container.querySelector('[aria-hidden]') as HTMLElement).style.width).toBe('0%');
    rerender(<BarCell value={500} max={100} text="500" />);
    expect((container.querySelector('[aria-hidden]') as HTMLElement).style.width).toBe('100%');
  });
});

describe('Segmented', () => {
  it('marks the chosen option and reports a new choice', async () => {
    const change = vi.fn();
    render(<Segmented label="Period" value={3} onChange={change} options={[{ value: 1, label: 'Month' }, { value: 3, label: '3 months' }]} />);
    expect(screen.getByRole('button', { name: '3 months' }).getAttribute('aria-pressed')).toBe('true');
    await userEvent.click(screen.getByRole('button', { name: 'Month' }));
    expect(change).toHaveBeenCalledWith(1);
  });
});

describe('PageHeader, Skeleton and EmptyState', () => {
  it('puts the long explanation behind About this page and the actions at the right', () => {
    render(<PageHeader title="Net income" subtitle="By client" about={<p>Revenue comes from HaloPSA.</p>} actions={<button>Refresh</button>} />);
    const header = screen.getByTestId('page-header');
    expect(within(header).getByRole('heading', { name: 'Net income' })).toBeTruthy();
    expect(within(header).getByText('About this page')).toBeTruthy();
    expect(within(header).getByRole('button', { name: 'Refresh' })).toBeTruthy();
  });
  it('renders loading rows and an empty state with a reason and an action', () => {
    const { rerender } = render(<SkeletonRows rows={3} cols={2} />);
    expect(screen.getByRole('status', { name: 'Loading' }).querySelectorAll('[data-testid="skeleton"]').length).toBe(6);
    rerender(<EmptyState title="Nothing yet" why="CORE has not sent this." action={<button>Check CORE</button>} />);
    expect(screen.getByText('CORE has not sent this.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Check CORE' })).toBeTruthy();
    rerender(<Skeleton className="h-4" />);
    expect(screen.getByTestId('skeleton').getAttribute('aria-hidden')).toBe('true');
  });
});
