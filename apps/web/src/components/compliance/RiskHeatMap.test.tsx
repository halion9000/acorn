import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ heatmap: vi.fn() }));
vi.mock('@/lib/api', () => ({ riskRegisterApi: api }));

import { RiskHeatMap, asOfChoices } from './RiskHeatMap';

const cells = (filled: Record<string, string[]> = {}) =>
  [5, 4, 3, 2, 1].flatMap((l) =>
    [1, 2, 3, 4, 5].map((i) => ({ likelihood: l, impact: i, count: (filled[`${l}-${i}`] ?? []).length, level: l * i >= 16 ? 'critical' : l * i >= 10 ? 'high' : l * i >= 5 ? 'medium' : 'low', titles: filled[`${l}-${i}`] ?? [] })),
  );
const map = (over: Record<string, unknown> = {}) => ({
  as_of: '2026-11-18',
  kind: 'inherent',
  total: 2,
  by_level: { critical: 1, high: 0, medium: 1, low: 0 },
  cells: cells({ '4-4': ['Phishing'], '3-3': ['Backups'] }),
  trend: [
    { date: '2026-10-31', total: 1, critical: 0, high: 0, medium: 1, low: 0 },
    { date: '2026-11-18', total: 2, critical: 1, high: 0, medium: 1, low: 0 },
  ],
  approximate_before: null,
  ...over,
});

beforeEach(() => {
  api.heatmap.mockReset();
  api.heatmap.mockResolvedValue(map());
});

describe('asOfChoices', () => {
  it('offers today and the last day of each of the twelve months before this one, newest first', () => {
    const c = asOfChoices(new Date(Date.UTC(2026, 10, 18)));
    expect(c).toHaveLength(13);
    expect(c[0]).toEqual({ value: '', label: 'Today' });
    expect(c[1]).toEqual({ value: '2026-10-31', label: 'October 2026 (end)' });
    expect(c[12].value).toBe('2025-11-30');
  });
});

describe('RiskHeatMap', () => {
  it('shows the counts in the cells, the summary line and the month by month table', async () => {
    render(<RiskHeatMap clientId="c1" />);
    expect(await screen.findByTestId('heatmap-grid')).toBeTruthy();
    expect(screen.getByTestId('heat-4-4')).toHaveTextContent('1');
    expect(screen.getByTestId('heat-4-4')).toHaveAttribute('title', 'Phishing');
    expect(screen.getByTestId('heat-1-1')).toHaveTextContent('');
    expect(screen.getByTestId('heatmap-summary')).toHaveTextContent('2 risks on 2026-11-18: 1 critical, 0 high, 1 medium, 0 low.');
    expect(screen.getByTestId('heatmap-trend')).toHaveTextContent('2026-10-31');
    expect(api.heatmap).toHaveBeenCalledWith('c1', 'inherent', '');
  });

  it('asks again for the after-treatment levels and for an earlier month when those are chosen', async () => {
    const user = userEvent.setup();
    render(<RiskHeatMap clientId="c1" />);
    await screen.findByTestId('heatmap-grid');
    await user.selectOptions(screen.getByLabelText('Which levels'), 'residual');
    await waitFor(() => expect(api.heatmap).toHaveBeenLastCalledWith('c1', 'residual', ''));
    const earlier = asOfChoices(new Date())[2].value;
    await user.selectOptions(screen.getByLabelText('As of'), earlier);
    await waitFor(() => expect(api.heatmap).toHaveBeenLastCalledWith('c1', 'residual', earlier));
  });

  it('says so when the map cannot be loaded', async () => {
    api.heatmap.mockRejectedValue(new Error('nope'));
    render(<RiskHeatMap clientId="c1" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the heat map.');
  });
});
