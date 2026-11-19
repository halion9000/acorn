import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ScorecardSettingsView, worked, type Template } from './ScorecardSettingsView';

const TEMPLATE: Template = {
  total_weight: 4,
  metrics: [
    { metric: 'Tickets Closed', unit: 'tickets', weight: 3, share: 75, floor: 0, by_days_worked: true, tables: { '5': [[30, 5], [24, 4]], '4': [[24, 5]] } },
    { metric: 'CSAT', unit: 'average survey score (1-5)', weight: 1, share: 25, floor: 0, by_days_worked: false, tables: { any: [[5, 5], [4, 4]] } },
  ],
  grades: [{ grade: 'S', from: 4.5 }, { grade: 'F', from: 0 }],
};

afterEach(() => cleanup());

describe('the worked example', () => {
  it('multiplies each score by its weight and divides by the weights that were scored', () => {
    const r = worked(TEMPLATE.metrics, { 'Tickets Closed': 4, CSAT: 5 });
    expect(r.rows.map((x) => x.points)).toEqual([12, 5]);
    expect(r.total).toBe(4.3);
    expect(worked(TEMPLATE.metrics, { CSAT: 2 }).total).toBe(2);
    expect(worked(TEMPLATE.metrics, {}).total).toBe(0);
  });
});

describe('the Scorecard settings page', () => {
  it('shows the weights with their share, the brackets by days worked, the grades and a link back', async () => {
    authFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(TEMPLATE) });
    render(<ScorecardSettingsView />);
    const weights = await screen.findByTestId('score-weights');
    expect(within(weights).getByText('75%')).toBeInTheDocument();
    expect(within(weights).getByText('Total weight 4.')).toBeInTheDocument();
    const closed = screen.getByTestId('score-brackets-tickets-closed');
    expect(within(closed).getByText('30 or more: 5 · 24 or more: 4')).toBeInTheDocument();
    expect(within(closed).getByText('4 days')).toBeInTheDocument();
    expect(within(screen.getByTestId('score-brackets-csat')).getByText('Any week')).toBeInTheDocument();
    expect(within(screen.getByTestId('score-grades')).getByText('4.5 or more')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to the scorecard' })).toHaveAttribute('href', '/metrics/scorecard');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/metrics/scorecard-template');
  });
});
